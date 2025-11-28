import json
import logging

from langgraph.graph import END, StateGraph

from sql_query_assistant import (
    OpenAILLMClient,
    Settings,
    WorkflowState,
    build_interpreter_subgraph,
    build_persistence_subgraph,
    build_sql_drafter_subgraph,
    create_llm_client,
    load_assumption_catalog,
    load_table_cards,
)

logger = logging.getLogger(__name__)


def build_main_graph(client: OpenAILLMClient, settings: Settings):
    """
    Compose the main graph by nesting the interpreter subgraph.

    Args:
        client: LLM client instance for making LLM calls
        settings: Settings instance for downstream modules (e.g., persistence)

    Returns:
        Compiled LangGraph workflow runnable for the main workflow.
    """
    interpreter_runnable = build_interpreter_subgraph(client)
    sql_drafter_runnable = build_sql_drafter_subgraph(client)
    persistence_runnable = build_persistence_subgraph(settings)

    workflow = StateGraph(WorkflowState)
    workflow.add_node("interpreter", interpreter_runnable)
    workflow.add_node("sql_drafter", sql_drafter_runnable)
    workflow.add_node("persistence", persistence_runnable)

    workflow.set_entry_point("interpreter")
    workflow.add_edge("interpreter", "sql_drafter")
    workflow.add_edge("sql_drafter", "persistence")
    workflow.add_edge("persistence", END)

    return workflow.compile()


def main():
    """Run the query interpreter workflow."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    logger.info("Loading table cards and assumption catalog...")
    settings = Settings()
    table_cards = load_table_cards(settings=settings)
    assumption_catalog = load_assumption_catalog(settings=settings)

    llm_client = create_llm_client(settings=settings)

    logger.info("Building workflow graph...")
    main_graph = build_main_graph(llm_client, settings)

    user_query = "Show me the count of cases for young Adults broken down by sex."

    initial_state: WorkflowState = {
        "user_query": user_query,
        "table_cards": table_cards,
        "assumption_catalog": assumption_catalog,
    }

    logger.info("Processing query: %s", initial_state["user_query"])

    result_state = main_graph.invoke(initial_state)

    logger.info("Intent Card:\n%s", json.dumps(result_state["intent_card"].model_dump(), indent=2))
    logger.info("SQL Draft:\n%s", json.dumps(result_state["sql_draft"].model_dump(), indent=2))

    logger.info("Results saved with run_id=%s", result_state.get("run_id"))


if __name__ == "__main__":
    main()
