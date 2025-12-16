from functools import partial

from langchain_core.runnables import Runnable
from langgraph.graph import END, StateGraph

from .nodes import draft_sql
from sql_query_assistant.llm_client import OpenAILLMClient
from sql_query_assistant.config import Settings
from sql_query_assistant.state import WorkflowState


def build_sql_drafter_subgraph(client: OpenAILLMClient, settings: Settings) -> Runnable:
    """
    Build the SQL drafter subgraph.

    Args:
        client: LLM client instance for making LLM calls.
        settings: Settings instance for target SQL dialect configuration.

    Returns:
        Compiled LangGraph workflow runnable for the SQL drafter module.
    """
    workflow = StateGraph(WorkflowState)

    draft_sql_node = partial(draft_sql, client=client, settings=settings)

    workflow.add_node("draft_sql", draft_sql_node)

    workflow.set_entry_point("draft_sql")
    workflow.add_edge("draft_sql", END)

    return workflow.compile()
