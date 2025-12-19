import re
import time
import sqlite3

from pathlib import Path
from typing import Any

DANGEROUS_SQL_PATTERNS = [
    r";\s*DROP",
    r";\s*DELETE",
    r";\s*UPDATE",
    r"--\s*[^\n]", # comments that aren't at end of line
]

AGG_FUNCTIONS = ("COUNT", "SUM", "AVG", "MIN", "MAX")

CLAUSE_FLAGS = {
    "has_group_by": "GROUP BY",
    "has_where": "WHERE",
    "has_order_by": "ORDER BY",
}


def _normalized_sql(sql: str) -> str:
    return sql.upper().strip()


def _find_dangerous_pattern(sql_upper: str) -> str | None:
    for pattern in DANGEROUS_SQL_PATTERNS:
        if re.search(pattern, sql_upper):
            return pattern
    return None


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
    sql_upper = _normalized_sql(sql)

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
    dangerous_pattern = _find_dangerous_pattern(sql_upper)
    if dangerous_pattern:
        return False, f"Potentially dangerous SQL pattern detected: {dangerous_pattern}"

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
                "rows": [dict(row) for row in rows[:100]],  # limit to 100 rows for memory
            }

            return True, result, None

    except sqlite3.Error as e:
        return False, None, f"SQL execution error: {str(e)}"
    except Exception as e:
        return False, None, f"Unexpected error: {str(e)}"



def validate_semantic_expectations(sql: str, expected: dict) -> tuple[bool, list[str]]:
    """
    Validate that SQL meets semantic expectations.

    Args:
        sql: SQL query to validate
        expected: Dictionary of expected properties

    Returns:
        Tuple of (all_passed, list_of_failures)
    """
    failures = []
    sql_upper = _normalized_sql(sql)

    def check_expected_items(key: str, label: str) -> None:
        for item in expected.get(key, []):
            if item.upper() not in sql_upper:
                failures.append(f"Expected {label} '{item}' not found in SQL")

    # Check expected tables
    check_expected_items("tables", "table")

    # Check expected keywords
    check_expected_items("keywords", "keyword")

    # Check expected columns
    check_expected_items("columns", "column")

    # Check for aggregation
    if expected.get("has_aggregation"):
        if not any(func in sql_upper for func in AGG_FUNCTIONS):
            failures.append("Expected aggregation function (COUNT/SUM/AVG/MIN/MAX) not found")

    # Check for common clause flags
    for flag, clause in CLAUSE_FLAGS.items():
        if expected.get(flag) and clause not in sql_upper:
            failures.append(f"Expected {clause} clause not found")

    # Check for LIMIT/TOP
    if expected.get("has_limit"):
        if "LIMIT" not in sql_upper and "TOP" not in sql_upper:
            failures.append("Expected LIMIT/TOP clause not found")

    # Check for operators
    if expected.get("operators"):
        # Accept if ANY of the expected operators is present
        operators_found = any(op.upper() in sql_upper for op in expected["operators"])
        if not operators_found:
            failures.append(f"None of expected operators {expected['operators']} found in SQL")

    # Check for logical operators
    if expected.get("logical_operators"):
        for operator in expected["logical_operators"]:
            if operator.upper() not in sql_upper:
                failures.append(f"Expected logical operator '{operator}' not found")

    return len(failures) == 0, failures


def validate_result_expectations(result: dict, expected: dict) -> tuple[bool, list[str]]:
    """
    Validate execution results meet expectations.

    Args:
        result: Execution result dictionary
        expected: Dictionary of expected properties

    Returns:
        Tuple of (all_passed, list_of_failures)
    """
    failures = []

    # Check minimum row count
    if "min_rows" in expected:
        if result["row_count"] < expected["min_rows"]:
            failures.append(
                f"Expected at least {expected['min_rows']} rows, got {result['row_count']}"
            )

    # Check maximum row count
    if "max_rows" in expected:
        if result["row_count"] > expected["max_rows"]:
            failures.append(
                f"Expected at most {expected['max_rows']} rows, got {result['row_count']}"
            )

    # Check result shape for aggregations
    if expected.get("result_shape") == "single_value":
        if result["row_count"] != 1 or len(result["column_names"]) != 1:
            failures.append(
                f"Expected single value result (1 row, 1 column), "
                f"got {result['row_count']} rows, {len(result['column_names'])} columns"
            )

    # Check that specific columns are present
    if "columns" in expected:
        result_columns_upper = {col.upper() for col in result["column_names"]}
        for expected_col in expected["columns"]:
            if expected_col.upper() not in result_columns_upper:
                failures.append(f"Expected column '{expected_col}' not in result columns")

    return len(failures) == 0, failures
