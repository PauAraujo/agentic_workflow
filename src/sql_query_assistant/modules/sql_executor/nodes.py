import logging

from sql_query_assistant.state import WorkflowState
from sql_query_assistant.domain import QueryResult
from sql_query_assistant.config import Settings
from sql_query_assistant.database import create_backend

logger = logging.getLogger(__name__)


def _make_failed_query_state(error_message: str) -> dict:
    """
    Create a failed query result with error message.

    Args:
        error_message: Description of the error

    Returns:
        Partial state update containing failed QueryResult
    """
    return {
        "query_result": QueryResult(
            success=False,
            row_count=0,
            error_message=error_message
        )
    }


def execute_sql(state: WorkflowState, settings: Settings) -> dict:
    """
    Execute the generated SQL query against the database.

    Args:
        state: Current workflow state containing sql_draft
        settings: Settings instance for database configuration

    Returns:
        Partial state update containing query_result
    """
    sql_draft = state.get("sql_draft")

    if not sql_draft:
        logger.warning("No SQL draft found in state; skipping execution")
        return _make_failed_query_state("No SQL draft available to execute")

    executable_sql = sql_draft.sql

    logger.info("Executing SQL")
    logger.debug("SQL (dialect: %s): %s", settings.target_sql_dialect, executable_sql[:100])

    try:
        backend = create_backend(settings)
        result_rows, column_names, execution_time_ms = backend.execute_query(executable_sql)
        row_count = len(result_rows)

        logger.info("Query executed successfully: %d rows returned in %.2fms", row_count, execution_time_ms)

        return {
            "query_result": QueryResult(
                success=True,
                row_count=row_count,
                column_names=column_names,
                rows=result_rows,
                execution_time_ms=execution_time_ms
            )
        }

    except Exception as e:
        logger.error("SQL execution failed: %s", str(e))
        return _make_failed_query_state(f"SQL execution error: {str(e)}")
