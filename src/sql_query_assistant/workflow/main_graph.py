import logging

from functools import partial
from langgraph.graph import END, StateGraph

from sql_query_assistant.config import Settings
from sql_query_assistant.domain import QueryResult
from sql_query_assistant.llm_client import LLMClient
from sql_query_assistant.state import WorkflowState
from sql_query_assistant.modules.table_card_retriever import retrieve_relevant_table_cards
from sql_query_assistant.modules.table_selector import select_tables
from sql_query_assistant.modules.sql_drafter import draft_sql
from sql_query_assistant.modules.sql_validator import validate_sql
from sql_query_assistant.modules.sql_repairer import repair_sql
from sql_query_assistant.modules.sql_executor import execute_sql
from sql_query_assistant.persistence import persist_results


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
    client: LLMClient,
    settings: Settings,
    enable_persistence: bool = True,
):
    """
    Compose the main graph with per-agent model configuration.

    Workflow:
    1. table_card_retriever -> table_selector (RAG-based table selection + refinement)
    2. table_selector -> sql_drafter (generate SQL from user query and table cards)
    3. sql_drafter -> sql_validator
    4. sql_validator -> (if valid) sql_executor
                     -> (if invalid and attempts < max) sql_repairer
                     -> (if invalid and attempts >= max) validation_failed (no execution)
    5. sql_repairer -> sql_validator (retry validation)
    6. sql_executor/validation_failed -> persistence (optional) -> END

    Logic:
        - The RAG Retriever uses Azure AI Search to select relevant table cards
        - The Table Selector refines table selection using LLM reasoning
        - The SQL Drafter generates SQL directly from the user query and table metadata
        - The Validator checks syntax and semantics
        - If validation fails, the Repairer attempts to fix the SQL based on errors
        - The loop (Repair -> Validate) continues until the query passes or max_retries is hit

    Args:
        client: LLM client supporting multiple providers
        settings: Settings instance with agent configurations
        enable_persistence: Whether to include persistence in the workflow

    Returns:
        The executable LangGraph workflow (compiled StateGraph) ready for invocation
    """
    # Build RAG retriever node for table card selection
    table_card_retriever_node = partial(
        retrieve_relevant_table_cards,
        settings=settings,
    )

    # Build table selector node for refining table selection
    table_selector_node = partial(
        select_tables,
        client=client,
        model_config=settings.agents.table_selector,
        settings=settings,
    )

    # Bind dependencies to node functions with agent-specific configs
    sql_drafter_node = partial(
        draft_sql,
        client=client,
        model_config=settings.agents.drafter,
        target_dialect=settings.target_sql_dialect,
    )

    sql_validator_node = partial(
        validate_sql,
        settings=settings,
    )

    sql_repairer_node = partial(
        repair_sql,
        client=client,
        model_config=settings.agents.repairer,
        target_dialect=settings.target_sql_dialect,
        max_repair_attempts=settings.max_repair_attempts,
    )

    sql_executor_node = partial(
        execute_sql,
        settings=settings,
    )

    route_func = partial(
        route_after_validation,
        settings=settings,
    )

    workflow = StateGraph(WorkflowState)
    workflow.add_node("table_card_retriever", table_card_retriever_node)
    workflow.add_node("table_selector", table_selector_node)
    workflow.add_node("sql_drafter", sql_drafter_node)
    workflow.add_node("sql_validator", sql_validator_node)
    workflow.add_node("sql_repairer", sql_repairer_node)
    workflow.add_node("sql_executor", sql_executor_node)
    workflow.add_node("validation_failed", validation_failed_node)

    # Build workflow edges
    workflow.set_entry_point("table_card_retriever")
    workflow.add_edge("table_card_retriever", "table_selector")
    workflow.add_edge("table_selector", "sql_drafter")
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
