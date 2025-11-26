import json

from langgraph.graph import END, StateGraph

from sql_query_assistant import (
    WorkflowState,
    OpenAILLMClient,
    build_interpreter_subgraph,
    create_llm_client,
    load_assumption_catalog,
    load_table_cards,
)


def build_main_graph(client: OpenAILLMClient):
    """
    Compose the main graph by nesting the interpreter subgraph.

    Args:
        client: LLM client instance for making LLM calls

    Returns:
        Compiled LangGraph workflow runnable for the main workflow.
    """
    interpreter_runnable = build_interpreter_subgraph(client)

    workflow = StateGraph(WorkflowState)
    workflow.add_node("interpreter", interpreter_runnable)

    workflow.set_entry_point("interpreter")
    workflow.add_edge("interpreter", END)

    return workflow.compile()


def main():
    """Run the query interpreter workflow."""
    print("Loading table cards and assumption catalog...")
    table_cards = load_table_cards()
    assumption_catalog = load_assumption_catalog()

    llm_client = create_llm_client()

    print("Building workflow graph...")
    main_graph = build_main_graph(llm_client)

    user_query = "Show me the count of cases for young Adults broken down by sex."

    initial_state: WorkflowState = {
        "user_query": user_query,
        "table_cards": table_cards,
        "assumption_catalog": assumption_catalog,
    }

    print(f"\nProcessing query: {initial_state['user_query']}")
    print("-" * 80)

    result_state = main_graph.invoke(initial_state)

    print("\nIntent Card:")
    print(json.dumps(result_state["intent_card"].model_dump(), indent=2))


if __name__ == "__main__":
    main()
