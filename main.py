import sys
import json
import logging
import argparse

from pathlib import Path
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


def build_main_graph(
    client: OpenAILLMClient,
    settings: Settings,
    enable_persistence: bool = True,
):
    """
    Compose the main graph by nesting the interpreter subgraph.

    Args:
        client: LLM client instance for making LLM calls
        settings: Settings instance for downstream modules (e.g., persistence)
        enable_persistence: Whether to include persistence in the workflow

    Returns:
        Compiled LangGraph workflow runnable for the main workflow.
    """
    interpreter_runnable = build_interpreter_subgraph(client)
    sql_drafter_runnable = build_sql_drafter_subgraph(client)

    workflow = StateGraph(WorkflowState)
    workflow.add_node("interpreter", interpreter_runnable)
    workflow.add_node("sql_drafter", sql_drafter_runnable)

    workflow.set_entry_point("interpreter")
    workflow.add_edge("interpreter", "sql_drafter")

    if enable_persistence:
        persistence_runnable = build_persistence_subgraph(settings)
        workflow.add_node("persistence", persistence_runnable)
        workflow.add_edge("sql_drafter", "persistence")
        workflow.add_edge("persistence", END)
    else:
        workflow.add_edge("sql_drafter", END)

    return workflow.compile()


def run_workflow(
    user_query: str,
    settings: Settings,
    table_cards_path: Path | None = None,
    assumptions_path: Path | None = None,
    enable_persistence: bool = True,
) -> WorkflowState:
    """
    Run the end-to-end workflow for a single query.

    Args:
        user_query: Natural language query to convert to SQL.
        settings: Settings instance for LLM + persistence.
        table_cards_path: Optional override for table cards directory.
        assumptions_path: Optional override for assumptions catalog file.
        enable_persistence: Whether to run the persistence step.

    Returns:
        Final workflow state containing intent card, SQL draft, and optional run_id.
    """
    logger.info("Loading table cards and assumption catalog...")
    table_cards = load_table_cards(settings=settings, base_path=table_cards_path)
    assumption_catalog = load_assumption_catalog(
        settings=settings,
        catalog_path=assumptions_path,
    )

    llm_client = create_llm_client(settings=settings)

    logger.info("Building workflow graph...")
    main_graph = build_main_graph(
        llm_client,
        settings,
        enable_persistence=enable_persistence,
    )

    initial_state: WorkflowState = {
        "user_query": user_query,
        "table_cards": table_cards,
        "assumption_catalog": assumption_catalog,
    }

    logger.info("Processing query: %s", initial_state["user_query"])
    return main_graph.invoke(initial_state)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="SQL Query Assistant - Convert natural language to SQL"
    )
    parser.add_argument(
        "query",
        nargs="?",
        help="Natural language query to convert to SQL",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--render-graph",
        action="store_true",
        help="Render the workflow graph to PNG and exit (no nodes are executed)",
    )
    parser.add_argument(
        "--render-graph-path",
        type=Path,
        help="Optional output path for the rendered workflow graph PNG",
    )
    parser.add_argument(
        "--table-cards-dir",
        type=Path,
        help="Override path to table cards directory",
    )
    parser.add_argument(
        "--assumptions-file",
        type=Path,
        help="Override path to assumptions catalog YAML file",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Run without writing outputs",
    )
    return parser.parse_args()


def main():
    """Run the query interpreter workflow via CLI."""
    args = parse_args()

    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    try:
        settings = Settings()

        if args.render_graph:
            output_path = args.render_graph_path or (
                settings.paths.output_dir / "graphs" / "main_graph.png"
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)

            llm_client = create_llm_client(settings=settings)
            main_graph = build_main_graph(
                llm_client,
                settings,
                enable_persistence=not args.no_persist,
            )

            graph = main_graph.get_graph()
            png_bytes = graph.draw_mermaid_png()
            output_path.write_bytes(png_bytes)

            logger.info(
                "Workflow graph rendered to %s (persistence %s)",
                output_path,
                "enabled" if not args.no_persist else "disabled",
            )
            sys.exit(0)

        user_query = args.query
        if not user_query:
            user_query = input("Enter your query: ").strip()
        if not user_query:
            logger.error("No query provided")
            sys.exit(1)

        result_state = run_workflow(
            user_query=user_query,
            settings=settings,
            table_cards_path=args.table_cards_dir,
            assumptions_path=args.assumptions_file,
            enable_persistence=not args.no_persist,
        )
    except Exception as exc:
        logger.exception("Workflow failed: %s", exc)
        sys.exit(2)

    logger.info(
        "Intent Card:\n%s",
        json.dumps(result_state["intent_card"].model_dump(), indent=2),
    )
    logger.info(
        "SQL Draft:\n%s",
        json.dumps(result_state["sql_draft"].model_dump(), indent=2),
    )

    if args.no_persist:
        logger.info("Persistence skipped (--no-persist)")
        result_state.pop("run_id", None)


if __name__ == "__main__":
    main()
