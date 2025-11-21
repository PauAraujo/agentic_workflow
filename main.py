import json

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from src import (
    AssumptionState,
    OpenAILLMClient,
    Settings,
    build_assumption_graph,
    load_assumption_catalog,
    load_table_cards,
)

def create_llm_client() -> OpenAILLMClient:
    """Create an OpenAILLMClient with Langfuse integration."""
    settings = Settings()
    handler = None
    if settings.langfuse is not None:
        # Initialize Langfuse (sets up global default client)
        Langfuse(
            public_key=settings.langfuse.public_key,
            secret_key=settings.langfuse.secret_key,
            host=str(settings.langfuse.host),
        )
        handler = CallbackHandler()
    return OpenAILLMClient.from_settings(settings, langfuse_handler=handler)

def main():
    """Run the assumptions agent workflow."""
    print("Loading table cards and assumption catalog...")
    table_cards = load_table_cards()
    assumption_catalog = load_assumption_catalog()

    llm_client = create_llm_client()

    print("Building workflow graph...")
    assumption_graph = build_assumption_graph(llm_client)

    initial_state: AssumptionState = {
        "user_query": "Show me case counts by age group and sex for adults in 2024",
        "table_cards": table_cards,
        "assumption_catalog": assumption_catalog,
    }

    print(f"\nProcessing query: {initial_state['user_query']}")
    print("-" * 80)

    result_state = assumption_graph.invoke(initial_state)

    print("\nIntent Card:")
    print(json.dumps(result_state["intent_card"].model_dump(), indent=2))


if __name__ == "__main__":
    main()