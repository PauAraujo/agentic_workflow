import time
import logging
import sqlite3

from sql_query_assistant.state import WorkflowState
from sql_query_assistant.domain import QueryResult
from sql_query_assistant.config import Settings

logger = logging.getLogger(__name__)


def _create_error_result(error_message: str) -> dict:
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


def execute_sql(state: WorkflowState, settings: Settings) -> WorkflowState:
    """
    Execute the generated SQL query against the database.

    Args:
        state: Current workflow state containing sql_draft
        settings: Settings instance for database path

    Returns:
        Partial state update containing query_result
    """
    sql_draft = state.get("sql_draft")

    if not sql_draft:
        logger.warning("No SQL draft found in state; skipping execution")
        return _create_error_result("No SQL draft available to execute")

    db_path = settings.paths.database_file

    if not db_path.exists():
        logger.error("Database file not found: %s", db_path)
        return _create_error_result(f"Database file not found: {db_path}")

    logger.info("Executing SQL against database: %s", db_path)
    logger.debug("SQL: %s", sql_draft.sql)

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row  # Enable column name access
            cursor = conn.cursor()

            start_time = time.perf_counter()
            cursor.execute(sql_draft.sql)
            execution_time_ms = (time.perf_counter() - start_time) * 1000

            rows = cursor.fetchall()
            column_names = [description[0] for description in cursor.description] if cursor.description else []

            # Convert rows to list of dicts
            result_rows = [dict(row) for row in rows]
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

    except sqlite3.Error as e:
        logger.error("SQL execution failed: %s", str(e))
        return _create_error_result(f"SQL execution error: {str(e)}")

    except Exception as e:
        logger.exception("Unexpected error during SQL execution")
        return _create_error_result(f"Unexpected error: {str(e)}")