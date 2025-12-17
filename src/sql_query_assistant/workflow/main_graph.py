import logging

from langgraph.graph import END, StateGraph

from ..config import Settings
from ..domain import QueryResult
from ..llm_client import OpenAILLMClient
from ..state import WorkflowState
from ..modules.interpreter import build_interpreter_subgraph
from ..modules.persistence import build_persistence_subgraph
from ..modules.sql_drafter import build_sql_drafter_subgraph
from ..modules.sql_validator import build_sql_validator_subgraph
from ..modules.sql_repairer import build_sql_repairer_subgraph
from ..modules.sql_executor import build_sql_executor_subgraph


logger = logging.getLogger(__name__)


def create_validation_failed_node():
    """
    Create a node that surfaces validation failure without executing SQL.

    Returns:
        A node function that creates a QueryResult indicating validation failure.
    """
    def validation_failed_node(state: WorkflowState) -> WorkflowState:
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
    return validation_failed_node


def create_routing_function(settings: Settings):
    """
    Create a routing function that directs flow after validation.

    Args:
        settings: Settings instance containing max_repair_attempts configuration.

    Returns:
        A routing function that determines next node based on validation results.
    """
    def route_after_validation(state: WorkflowState) -> str:
        """
        Route based on validation result and repair attempts.

        Returns:
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
    return route_after_validation


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
    interpreter_runnable = build_interpreter_subgraph(client)
    sql_drafter_runnable = build_sql_drafter_subgraph(client, settings)
    sql_validator_runnable = build_sql_validator_subgraph(settings)
    sql_repairer_runnable = build_sql_repairer_subgraph(client, settings)
    sql_executor_runnable = build_sql_executor_subgraph(settings)

    # Create routing and failure handling functions
    validation_failed_node = create_validation_failed_node()
    route_after_validation = create_routing_function(settings)

    workflow = StateGraph(WorkflowState)
    workflow.add_node("interpreter", interpreter_runnable)
    workflow.add_node("sql_drafter", sql_drafter_runnable)
    workflow.add_node("sql_validator", sql_validator_runnable)
    workflow.add_node("sql_repairer", sql_repairer_runnable)
    workflow.add_node("sql_executor", sql_executor_runnable)
    workflow.add_node("validation_failed", validation_failed_node)

    # Build workflow edges
    workflow.set_entry_point("interpreter")
    workflow.add_edge("interpreter", "sql_drafter")
    workflow.add_edge("sql_drafter", "sql_validator")

    # Conditional routing after validation
    workflow.add_conditional_edges(
        "sql_validator",
        route_after_validation,
        {
            "sql_executor": "sql_executor",
            "sql_repairer": "sql_repairer",
            "validation_failed": "validation_failed",
        }
    )

    # After repair, go back to validation
    workflow.add_edge("sql_repairer", "sql_validator")

    if enable_persistence:
        persistence_runnable = build_persistence_subgraph(settings)
        workflow.add_node("persistence", persistence_runnable)
        workflow.add_edge("sql_executor", "persistence")
        workflow.add_edge("validation_failed", "persistence")
        workflow.add_edge("persistence", END)
    else:
        workflow.add_edge("sql_executor", END)
        workflow.add_edge("validation_failed", END)

    return workflow.compile()
