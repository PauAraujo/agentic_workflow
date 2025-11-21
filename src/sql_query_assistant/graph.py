import io

from PIL import Image
from pathlib import Path
from functools import partial
from langgraph.graph import StateGraph, END
from langchain_core.runnables import Runnable

from .models import InterpreterState
from .llm_client import OpenAILLMClient
from .agents import interpret_query, build_intent_card
from .constants import GRAPH_DIAGRAM_PATH

def build_interpreter_graph(client: OpenAILLMClient) -> Runnable:
    """
    Build and compile the query interpretation workflow graph.

    Args:
        client: LLM client instance for making LLM calls

    Returns:
        Compiled LangGraph workflow
    """

    # Create workflow
    workflow = StateGraph(InterpreterState)

    # Create partial functions with client bound
    interpret_query_node = partial(
        interpret_query,
        client=client,
    ) #  shortcut to avoid writing a tiny wrapper function

    # Register nodes
    workflow.add_node("interpret_query", interpret_query_node)
    workflow.add_node("build_intent_card", build_intent_card)

    # Define edges
    workflow.set_entry_point("interpret_query")
    workflow.add_edge("interpret_query", "build_intent_card")
    workflow.add_edge("build_intent_card", END)

    chain = workflow.compile()

    # Generate and export graph visualization
    graph_png = chain.get_graph().draw_mermaid_png(max_retries=5, retry_delay=2.0)
    GRAPH_DIAGRAM_PATH.write_bytes(graph_png)
    #Image.open(io.BytesIO(graph_png)).show()

    return chain