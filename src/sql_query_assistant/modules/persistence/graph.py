from functools import partial

from langchain_core.runnables import Runnable
from langgraph.graph import END, StateGraph

from sql_query_assistant.config import Settings
from sql_query_assistant.state import WorkflowState

from .nodes import persist_results


def build_persistence_subgraph(settings: Settings) -> Runnable:
    """
    Build a persistence subgraph to save workflow artifacts.

    Args:
        settings: Settings instance providing output paths and other config.

    Returns:
        Compiled LangGraph runnable that writes CSV + JSON artifacts.
    """
    workflow = StateGraph(WorkflowState)

    persist_node = partial(persist_results, settings=settings)
    workflow.add_node("persist_results", persist_node)

    workflow.set_entry_point("persist_results")
    workflow.add_edge("persist_results", END)

    return workflow.compile()
