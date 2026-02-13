import sys
import json
import logging
import argparse

from dotenv import load_dotenv

from sql_query_assistant import Settings, WorkflowState
from sql_query_assistant.workflow import WorkflowRunner

logger = logging.getLogger(__name__)

load_dotenv(override=True)


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
        "--schemas",
        nargs="+",
        help="Schema names to load table cards from (e.g., ICSR ICSR_LOOKUP). Defaults to all schemas in table_cards_dir.",
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
            logger.warning(
                "Validation errors: %s", validation_result.get_error_summary()
            )

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
    if query_result is None:
        logger.error("Execution skipped (validation failed)")
        logger.error("SQL draft with validation errors is available in state dump")
    elif query_result.success:
        logger.info(
            "SQL execution succeeded: %d rows, %.2f ms, columns=%s",
            query_result.row_count,
            query_result.execution_time_ms or 0.0,
            query_result.column_names,
        )
        # show a small sample
        logger.debug("First rows: %s", query_result.rows[:3])
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

        user_query = args.query
        if not user_query:
            user_query = input("Enter your query: ").strip()
        if not user_query:
            logger.error("No query provided")
            sys.exit(1)

        settings.persist_enabled = not args.no_persist

        runner = WorkflowRunner(settings)
        result_state = runner.run(
            query=user_query,
            schemas=args.schemas,
        )

        log_workflow_results(result_state)
    except Exception as exc:
        logger.exception("Workflow failed: %s", exc)
        sys.exit(2)

    sql_draft = result_state.get("sql_draft")
    if sql_draft:
        logger.info(
            "SQL Draft:\n%s",
            json.dumps(sql_draft.model_dump(), indent=2),
        )
    else:
        logger.info("SQL Draft: (not available)")

    if args.no_persist:
        logger.info("Persistence skipped (--no-persist)")
        result_state.pop("run_id", None)


if __name__ == "__main__":
    main()
