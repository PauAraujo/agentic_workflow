from functools import partial
from langgraph.graph import StateGraph, END
from langchain_openai import AzureChatOpenAI
from IPython.display import Image, display

from .models import AssumptionState
from .agents import select_assumptions, build_intent_card


def build_assumption_graph(
    llm: AzureChatOpenAI,
    langfuse_handler
):
    """
    Build and compile the assumption selection workflow graph.

    Args:
        llm: Language model instance to use
        langfuse_handler: Langfuse callback handler for tracing

    Returns:
        Compiled LangGraph workflow
    """
    # Create workflow
    workflow = StateGraph(AssumptionState)

    # Create partial functions with LLM and handler bound
    select_assumptions_node = partial(
        select_assumptions,
        llm=llm,
        langfuse_handler=langfuse_handler
    ) #  shortcut to avoid writing a tiny wrapper function

    # Register nodes
    workflow.add_node("select_assumptions", select_assumptions_node)
    workflow.add_node("build_intent_card", build_intent_card)

    # Define edges
    workflow.set_entry_point("select_assumptions")
    workflow.add_edge("select_assumptions", "build_intent_card")
    workflow.add_edge("build_intent_card", END)

    # Compile
    chain = workflow.compile()

    # Show workflow
    print(chain.get_graph().draw_mermaid())
    #display(Image(chain.get_graph().draw_mermaid_png(draw_method=MermaidDrawMethod.PYPPETEER)))

    #display(Image(chain.get_graph().draw_mermaid_png(max_retries=5, retry_delay=2.0)))

    return chain