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


def execute_sql(state: WorkflowState, settings: Settings) -> dict:
    """
    Execute the generated SQL query against the database.

    If validation was performed, use the validated/converted SQL.
    Otherwise, fall back to manual conversion.

    Args:
        state: Current workflow state containing sql_draft and optional validation_result
        settings: Settings instance for database path

    Returns:
        Partial state update containing query_result
    """
    sql_draft = state.get("sql_draft")
    validation_result = state.get("validation_result")

    if not sql_draft:
        logger.warning("No SQL draft found in state; skipping execution")
        return _create_error_result("No SQL draft available to execute")

    # Block execution if validation failed (after repair attempts exhausted)
    if validation_result and not validation_result.is_valid:
        repair_attempts = state.get("repair_attempts", 0)
        logger.error(
            "Execution blocked due to validation failures after %d repair attempts: %s",
            repair_attempts,
            validation_result.get_error_summary()
        )
        return {
            "query_result": QueryResult(
                success=False,
                row_count=0,
                error_message=f"Validation failed: {validation_result.get_error_summary()}",
                validation_failed=True
            )
        }

    db_path = settings.paths.database_file

    if not db_path.exists():
        logger.error("Database file not found: %s", db_path)
        return _create_error_result(f"Database file not found: {db_path}")

    executable_sql = sql_draft.sql

    logger.info("Executing SQL against database: %s", db_path)
    logger.debug("SQL (dialect: %s): %s", sql_draft.dialect, executable_sql[:100])

    try:
        # Connect to in-memory database and attach the actual DB as ICSR schema
        # This allows queries to use Oracle-style schema.table notation (e.g., ICSR.PATIENT)
        with sqlite3.connect(":memory:") as conn:
            conn.row_factory = sqlite3.Row  # enable column name access
            cursor = conn.cursor()

            # Attach the database file under the ICSR schema alias
            cursor.execute("ATTACH DATABASE ? AS ICSR", (str(db_path),))

            start_time = time.perf_counter()
            cursor.execute(executable_sql)
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