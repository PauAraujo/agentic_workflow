from functools import partial

from langgraph.graph import StateGraph, END

from sql_query_assistant.config import Settings
from sql_query_assistant.state import WorkflowState
from .nodes import execute_sql


def build_sql_executor_subgraph(settings: Settings):
    """
    Build the SQL executor subgraph.

    Args:
        settings: Settings instance for database configuration

    Returns:
        Compiled LangGraph subgraph for SQL execution
    """
    subgraph = StateGraph(WorkflowState)

    # Bind settings to the execute_sql function
    execute_sql_with_settings = partial(execute_sql, settings=settings)

    subgraph.add_node("execute_sql", execute_sql_with_settings)
    subgraph.set_entry_point("execute_sql")
    subgraph.add_edge("execute_sql", END)

    return subgraph.compile()