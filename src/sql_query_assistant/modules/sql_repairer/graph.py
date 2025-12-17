from functools import partial

from langgraph.graph import StateGraph, END

from sql_query_assistant.llm_client import OpenAILLMClient
from sql_query_assistant.config import Settings
from sql_query_assistant.state import WorkflowState
from .nodes import repair_sql


def build_sql_repairer_subgraph(client: OpenAILLMClient, settings: Settings):
    """
    Build the SQL repairer subgraph.

    This subgraph uses an LLM to fix SQL queries that failed validation
    based on the validation errors provided.

    Args:
        client: LLM client for making repair calls
        settings: Settings instance for target SQL dialect configuration

    Returns:
        Compiled LangGraph subgraph for SQL repair
    """
    subgraph = StateGraph(WorkflowState)

    # Bind client and settings to the repair_sql function
    repair_sql_with_deps = partial(repair_sql, client=client, settings=settings)

    subgraph.add_node("repair_sql", repair_sql_with_deps)
    subgraph.set_entry_point("repair_sql")
    subgraph.add_edge("repair_sql", END)

    return subgraph.compile()
