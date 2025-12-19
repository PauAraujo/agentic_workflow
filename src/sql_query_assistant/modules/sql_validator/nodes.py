import logging
import sqlite3

from sqlglot import parse_one
from sqlglot.errors import ParseError, SqlglotError

from sql_query_assistant.state import WorkflowState
from sql_query_assistant.domain import ValidationResult
from sql_query_assistant.config import Settings

logger = logging.getLogger(__name__)


def validate_sql(state: WorkflowState, settings: Settings) -> dict:
    """
    Validate SQL using SQLGlot (syntax validation) and EXPLAIN (semantic validation).

    Since SQL is generated in the target dialect, we validate it directly without conversion.

    Validation steps:
    1. SQLGlot Parse: Check if SQL is syntactically valid
    2. EXPLAIN: Dry-run against actual database to catch schema errors

    Args:
        state: Current workflow state containing sql_draft
        settings: Settings instance for database path

    Returns:
        Partial state update containing validation_result
    """
    sql_draft = state.get("sql_draft")

    if not sql_draft:
        logger.warning("No SQL draft found in state; skipping validation")
        return {
            "validation_result": ValidationResult(
                original_sql="",
                syntax_errors=["No SQL draft available to validate"]
            )
        }

    sql = sql_draft.sql
    dialect = sql_draft.dialect
    logger.info("Validating SQL (dialect: %s): %s", dialect, sql[:100])

    # Initialize result
    result = ValidationResult(original_sql=sql)

    # SQLGlot syntax check
    try:
        parse_one(sql, read=dialect)
        logger.debug("SQLGlot syntax validation passed")
    except ParseError as e:
        error_msg = f"SQL syntax error: {str(e)}"
        result.syntax_errors.append(error_msg)
        logger.error(error_msg)
        return {"validation_result": result}
    except SqlglotError as e:
        error_msg = f"SQLGlot error: {str(e)}"
        result.syntax_errors.append(error_msg)
        logger.error(error_msg)
        return {"validation_result": result}

    # EXPLAIN validation (semantic check against database)
    db_path = settings.paths.database_file

    if not db_path.exists():
        error_msg = f"Database file not found: {db_path}"
        result.explain_errors.append(error_msg)
        logger.error(error_msg)
        return {"validation_result": result}

    try:
        # Connect to in-memory database and attach the actual DB as ICSR schema
        # This allows queries to use Oracle-style schema.table notation (e.g., ICSR.PATIENT)
        with sqlite3.connect(":memory:") as conn:
            cursor = conn.cursor()

            # Attach the database file under the ICSR schema alias
            cursor.execute("ATTACH DATABASE ? AS ICSR", (str(db_path),))

            # Use EXPLAIN QUERY PLAN for dry-run validation
            explain_sql = f"EXPLAIN QUERY PLAN {sql}"
            cursor.execute(explain_sql) # validator checks if the SQL is valid, not if it is safe
            # TODO: ensure connection is read-only
            #  or add a string check in the validator ensuring the query starts with SELECT or WITH

            # If we get here, the query is valid (no errors added)
            logger.info("SQL validation passed all checks")

    except sqlite3.Error as e:
        error_msg = f"EXPLAIN validation error: {str(e)}"
        result.explain_errors.append(error_msg)
        logger.error(error_msg)
        return {"validation_result": result}

    return {"validation_result": result}
