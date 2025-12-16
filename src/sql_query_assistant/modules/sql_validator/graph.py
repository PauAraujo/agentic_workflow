from functools import partial

from langgraph.graph import StateGraph, END

from sql_query_assistant.config import Settings
from sql_query_assistant.state import WorkflowState
from .nodes import validate_sql


def build_sql_validator_subgraph(settings: Settings):
    """
    Build the SQL validator subgraph.

    This subgraph validates SQL using:
    1. SQLGlot for syntax checking and dialect conversion
    2. EXPLAIN for semantic validation against the database

    Args:
        settings: Settings instance for database configuration

    Returns:
        Compiled LangGraph subgraph for SQL validation
    """
    subgraph = StateGraph(WorkflowState)

    # Bind settings to the validate_sql function
    validate_sql_with_settings = partial(validate_sql, settings=settings)

    subgraph.add_node("validate_sql", validate_sql_with_settings)
    subgraph.set_entry_point("validate_sql")
    subgraph.add_edge("validate_sql", END)

    return subgraph.compile()
