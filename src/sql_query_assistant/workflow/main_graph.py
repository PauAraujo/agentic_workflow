import logging

from functools import partial
from langgraph.graph import END, StateGraph

from ..config import Settings
from ..domain import QueryResult
from ..llm_client import OpenAILLMClient
from ..state import WorkflowState
from ..modules.interpreter import build_interpreter_subgraph
from ..modules.sql_drafter import draft_sql
from ..modules.sql_validator import validate_sql
from ..modules.sql_repairer import repair_sql
from ..modules.sql_executor import execute_sql
from ..persistence import persist_results


logger = logging.getLogger(__name__)


def validation_failed_node(state: WorkflowState) -> WorkflowState:
    """
    Node that surfaces validation failure without executing SQL.

    Args:
        state: Current workflow state containing validation_result.

    Returns:
        Partial state update with failed QueryResult.
    """
    validation_result = state.get("validation_result")
    error_summary = (
        validation_result.get_error_summary()
        if validation_result
        else "Validation failed (no details available)"
    )
    return {
        "query_result": QueryResult(
            success=False,
            row_count=0,
            error_message=f"Validation failed: {error_summary}",
            validation_failed=True,
        )
    }


def route_after_validation(state: WorkflowState, settings: Settings) -> str:
    """
    Route based on validation result and repair attempts.

    Args:
        state: Current workflow state containing validation_result and repair_attempts.
        settings: Settings instance containing max_repair_attempts configuration.

    Returns:
        Next node name:
        - "sql_executor" if validation passed
        - "sql_repairer" if validation failed and can retry
        - "validation_failed" if validation failed and max retries exceeded
    """
    validation_result = state.get("validation_result")
    repair_attempts = state.get("repair_attempts", 0)

    if not validation_result:
        logger.warning("No validation result found; treating as failure")
        return "validation_failed"

    if validation_result.is_valid:
        logger.info("Validation passed; proceeding to executor")
        return "sql_executor"

    # Validation failed
    if repair_attempts >= settings.max_repair_attempts:
        logger.warning(
            "Validation failed after %d repair attempts; reporting failure",
            repair_attempts
        )
        return "validation_failed"

    logger.info("Validation failed; attempting repair (attempt %d/%d)",
               repair_attempts + 1, settings.max_repair_attempts)
    return "sql_repairer"


def build_main_graph(
    client: OpenAILLMClient,
    settings: Settings,
    enable_persistence: bool = True,
):
    """
    Compose the main graph with validation and repair loop.

    Workflow:
    1. interpreter -> sql_drafter
    2. sql_drafter -> sql_validator
    3. sql_validator -> (if valid) sql_executor
                     -> (if invalid and attempts < max) sql_repairer
                     -> (if invalid and attempts >= max) validation_failed (no execution)
    4. sql_repairer -> sql_validator (retry validation)
    5. sql_executor/validation_failed -> persistence (optional) -> END

    Logic:
        - The Validator acts as a conditional entry point.
        - If validation fails, the Repairer attempts to fix the SQL based on errors.
        - The loop (Repair -> Validate) continues until the query passes or max_retries is hit.

    Args:
        client: LLM client instance for making LLM calls
        settings: Settings instance for downstream modules (e.g., persistence)
        enable_persistence: Whether to include persistence in the workflow

    Returns:
        The executable LangGraph workflow (compiled StateGraph) ready for invocation
    """
    # Build interpreter subgraph (multi-node)
    interpreter_runnable = build_interpreter_subgraph(client)

    # Bind dependencies to node functions using partial
    sql_drafter_node = partial(draft_sql, client=client, settings=settings)
    sql_validator_node = partial(validate_sql, settings=settings)
    sql_repairer_node = partial(repair_sql, client=client, settings=settings)
    sql_executor_node = partial(execute_sql, settings=settings)
    route_func = partial(route_after_validation, settings=settings)

    workflow = StateGraph(WorkflowState)
    workflow.add_node("interpreter", interpreter_runnable)
    workflow.add_node("sql_drafter", sql_drafter_node)
    workflow.add_node("sql_validator", sql_validator_node)
    workflow.add_node("sql_repairer", sql_repairer_node)
    workflow.add_node("sql_executor", sql_executor_node)
    workflow.add_node("validation_failed", validation_failed_node)

    # Build workflow edges
    workflow.set_entry_point("interpreter")
    workflow.add_edge("interpreter", "sql_drafter")
    workflow.add_edge("sql_drafter", "sql_validator")

    # Conditional routing after validation
    workflow.add_conditional_edges(
        "sql_validator",
        route_func,
        {
            "sql_executor": "sql_executor",
            "sql_repairer": "sql_repairer",
            "validation_failed": "validation_failed",
        }
    )

    # After repair, go back to validation
    workflow.add_edge("sql_repairer", "sql_validator")

    if enable_persistence:
        persistence_node = partial(persist_results, settings=settings)
        workflow.add_node("persistence", persistence_node)
        workflow.add_edge("sql_executor", "persistence")
        workflow.add_edge("validation_failed", "persistence")
        workflow.add_edge("persistence", END)
    else:
        workflow.add_edge("sql_executor", END)
        workflow.add_edge("validation_failed", END)

    return workflow.compile()
