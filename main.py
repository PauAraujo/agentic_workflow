import sys
import json
import logging
import argparse

from pathlib import Path

from sql_query_assistant import Settings, WorkflowState, create_llm_client
from sql_query_assistant.workflow import build_main_graph, run_workflow


logger = logging.getLogger(__name__)


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


def log_workflow_results(result_state: WorkflowState) -> None:
    """
    Log validation, repair, and execution results from workflow state.

    Args:
        result_state: Final workflow state containing results to log.
    """
    # Log validation results
    validation_result = result_state.get("validation_result")
    if validation_result:
        if validation_result.is_valid:
            logger.info("SQL validation: PASSED")
        else:
            logger.warning("SQL validation: FAILED")
            logger.warning("Validation errors: %s", validation_result.get_error_summary())

    # Log repair attempts and history
    repair_attempts = result_state.get("repair_attempts", 0)
    if repair_attempts > 0:
        logger.info("SQL repair attempts: %d", repair_attempts)
        repair_history = result_state.get("repair_history", [])
        if repair_history:
            logger.debug("Repair history: %d SQL drafts generated", len(repair_history))
            for i, draft in enumerate(repair_history, 1):
                logger.debug("  Repair attempt %d SQL: %s", i, draft.sql[:100])

    # Log execution results
    query_result = result_state.get("query_result")
    if query_result:
        if query_result.success:
            logger.info(
                "SQL execution succeeded: %d rows, %.2f ms, columns=%s",
                query_result.row_count,
                query_result.execution_time_ms or 0.0,
                query_result.column_names,
            )
            # show a small sample
            logger.debug("First rows: %s", query_result.rows[:3])
        else:
            if query_result.validation_failed:
                logger.error("Execution blocked: %s", query_result.error_message)
                logger.error("SQL draft with validation errors is available in state dump")
            else:
                logger.error("SQL execution failed: %s", query_result.error_message)


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

        log_workflow_results(result_state)
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
