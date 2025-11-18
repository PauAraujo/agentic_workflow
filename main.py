import json

from langfuse import get_client

from src import (
    get_llm,
    get_langfuse_handler,
    build_assumption_graph,
    load_table_cards,
    load_assumption_catalog,
    AssumptionState,
)


def main():
    """Run the assumptions agent workflow."""

    # Initialize Langfuse client (for tracking)
    langfuse = get_client()

    # Get Langfuse handler and LLM
    langfuse_handler = get_langfuse_handler()
    llm = get_llm(temperature=0.7)

    # Load data
    print("Loading table cards and assumption catalog...")
    table_cards = load_table_cards()
    assumption_catalog = load_assumption_catalog()

    # Build the workflow graph
    print("Building workflow graph...")
    assumption_graph = build_assumption_graph(llm, langfuse_handler)

    # Define initial state
    initial_state: AssumptionState = {
        "user_query": "Show me case counts by age group and sex for adults in 2024",
        "table_cards": table_cards,
        "assumption_catalog": assumption_catalog,
    }

    # Run the workflow
    print(f"\nProcessing query: {initial_state['user_query']}")
    print("-" * 80)

    result_state = assumption_graph.invoke(initial_state)

    # Display results
    print("\nIntent Card:")
    print(json.dumps(result_state["intent_card"], indent=2))


if __name__ == "__main__":
    main()