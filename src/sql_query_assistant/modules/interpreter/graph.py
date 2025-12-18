from functools import partial

from langchain_core.runnables import Runnable
from langgraph.graph import END, StateGraph

from .nodes import build_intent_card, interpret_query
from sql_query_assistant.llm_client import LLMClient
from sql_query_assistant.config import ModelConfig
from sql_query_assistant.state import WorkflowState

def build_interpreter_subgraph(
    client: LLMClient,
    model_config: ModelConfig,
) -> Runnable:
    """
    Build the interpreter subgraph with specified model configuration.

    Args:
        client: LLM client for making LLM calls
        model_config: Model configuration for the interpreter agent

    Returns:
        Compiled LangGraph workflow runnable for the interpreter module.
    """
    workflow = StateGraph(WorkflowState)

    interpret_query_node = partial(
        interpret_query,
        client=client,
        model_config=model_config,
    )

    workflow.add_node("interpret_query", interpret_query_node)
    workflow.add_node("build_intent_card", build_intent_card)

    workflow.set_entry_point("interpret_query")
    workflow.add_edge("interpret_query", "build_intent_card")
    workflow.add_edge("build_intent_card", END)

    return workflow.compile()
