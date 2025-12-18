import re
import sqlite3

from pathlib import Path
from typing import Any


def validate_sql_syntax(sql: str) -> tuple[bool, str | None]:
    """
    Validate SQL syntax by attempting to parse it.

    Args:
        sql: SQL query string to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not sql or not sql.strip():
        return False, "Empty SQL query"

    # basic syntax checks
    sql_upper = sql.upper().strip()

    # must start with SELECT
    if not sql_upper.startswith("SELECT"):
        return False, "SQL must start with SELECT"

    # must have FROM clause
    if "FROM" not in sql_upper:
        return False, "SQL missing FROM clause"

    # check for balanced parentheses
    if sql.count("(") != sql.count(")"):
        return False, "Unbalanced parentheses"

    # check for basic SQL injection patterns (paranoid check)
    dangerous_patterns = [
        r";\s*DROP",
        r";\s*DELETE",
        r";\s*UPDATE",
        r"--\s*[^\n]",  # comments that aren't at end of line
    ]
    for pattern in dangerous_patterns:
        if re.search(pattern, sql_upper):
            return False, f"Potentially dangerous SQL pattern detected: {pattern}"

    return True, None


def validate_sql_execution(sql: str, db_path: Path, timeout: int = 5) -> tuple[bool, dict[str, Any] | None, str | None]:
    """
    Validate SQL by executing it against the database.

    Args:
        sql: SQL query to execute
        db_path: Path to SQLite database file
        timeout: Query timeout in seconds

    Returns:
        Tuple of (success, result_dict, error_message)
        result_dict contains: row_count, column_names, execution_time_ms
    """
    if not db_path.exists():
        return False, None, f"Database not found: {db_path}"

    try:
        import time

        with sqlite3.connect(db_path, timeout=timeout) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            start_time = time.perf_counter()
            cursor.execute(sql)
            execution_time_ms = (time.perf_counter() - start_time) * 1000

            rows = cursor.fetchall()
            column_names = [desc[0] for desc in cursor.description] if cursor.description else []

            result = {
                "row_count": len(rows),
                "column_names": column_names,
                "execution_time_ms": execution_time_ms,
                "rows": [dict(row) for row in rows[:100]]  # limit to 100 rows for memory
            }

            return True, result, None

    except sqlite3.Error as e:
        return False, None, f"SQL execution error: {str(e)}"
    except Exception as e:
        return False, None, f"Unexpected error: {str(e)}"
