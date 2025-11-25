from functools import partial

from langchain_core.runnables import Runnable
from langgraph.graph import END, StateGraph

from .nodes import build_intent_card, interpret_query
from sql_query_assistant.llm_client import OpenAILLMClient
from sql_query_assistant.state import WorkflowState

def build_interpreter_subgraph(client: OpenAILLMClient) -> Runnable:
    """
    Build the interpreter subgraph that can be composed into larger workflows.

    Args:
        client: LLM client instance for making LLM calls

    Returns:
        Compiled LangGraph workflow runnable for the interpreter module.
    """
    workflow = StateGraph(WorkflowState)

    interpret_query_node = partial(interpret_query, client=client)

    workflow.add_node("interpret_query", interpret_query_node)
    workflow.add_node("build_intent_card", build_intent_card)

    workflow.set_entry_point("interpret_query")
    workflow.add_edge("interpret_query", "build_intent_card")
    workflow.add_edge("build_intent_card", END)

    return workflow.compile()
