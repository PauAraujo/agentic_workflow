import pytest
import sqlite3

from sql_query_assistant.domain import SQLDraft
from sql_query_assistant.modules.sql_validator.nodes import validate_sql


def _make_validator_state(sql):
    """Build a minimal workflow state for validator tests."""
    return {
        "sql_draft": SQLDraft(
            sql=sql,
            rationale="Test SQL",
        ),
    }


@pytest.fixture
def empty_db(dummy_settings):
    """Create an empty test database using schema convention."""
    db_dir = dummy_settings.paths.db_dir
    db_dir.mkdir(parents=True, exist_ok=True)

    # Create empty ICSR.db
    icsr_db_path = db_dir / "ICSR.db"
    sqlite3.connect(icsr_db_path).close()

    return dummy_settings


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id, name FROM ICSR.PATIENT WHERE id = 1",
        "SELECT * FROM ICSR.PATIENT",
    ],
)
def test_validate_sql_allows_basic_selects(db_with_patient_table, sql):
    """Valid SELECT queries should pass SQLGlot parse and EXPLAIN validation."""
    state = _make_validator_state(sql)

    result = validate_sql(state, db_with_patient_table)

    assert "validation_result" in result
    validation = result["validation_result"]

    assert validation.is_valid
    assert validation.sqlglot_parse_passed
    assert validation.explain_passed
    assert len(validation.syntax_errors) == 0
    assert len(validation.explain_errors) == 0


def test_validate_sql_fails_on_syntax_error(dummy_settings):
    """SQL with syntax errors should fail SQLGlot parsing."""
    state = _make_validator_state("SELECT * FROM WHERE invalid syntax ===")

    result = validate_sql(state, dummy_settings)

    validation = result["validation_result"]

    assert not validation.is_valid
    assert not validation.sqlglot_parse_passed
    assert len(validation.syntax_errors) > 0
    assert "syntax error" in validation.get_error_summary().lower()


def test_validate_sql_fails_on_schema_error(empty_db):
    """SQL referencing non-existent tables should fail EXPLAIN validation."""
    state = _make_validator_state("SELECT * FROM NONEXISTENT_TABLE")

    result = validate_sql(state, empty_db)

    validation = result["validation_result"]

    assert not validation.is_valid
    assert validation.sqlglot_parse_passed  # syntax is fine
    assert not validation.explain_passed  # but table doesn't exist
    assert len(validation.explain_errors) > 0


def test_validate_sql_uses_correct_dialect(db_with_patient_table):
    """Validator should use the dialect from settings for parsing."""
    state = _make_validator_state(sql="SELECT * FROM ICSR.PATIENT LIMIT 5")

    result = validate_sql(state, db_with_patient_table)

    validation = result["validation_result"]
    assert validation.is_valid


def test_validate_sql_handles_missing_sql_draft(dummy_settings):
    """Should return error result when sql_draft is missing from state."""
    state = {}  # no sql_draft :( and no table_cards

    result = validate_sql(state, dummy_settings)

    assert "validation_result" in result
    validation = result["validation_result"]
    assert not validation.is_valid
    assert len(validation.syntax_errors) > 0


@pytest.mark.parametrize(
    "operation, sql",
    [
        ("INSERT", "INSERT INTO ICSR.PATIENT (id, name) VALUES (1, 'test')"),
        ("UPDATE", "UPDATE ICSR.PATIENT SET name = 'hacked' WHERE id = 1"),
        ("DELETE", "DELETE FROM ICSR.PATIENT WHERE id = 1"),
    ],
)
def test_validate_sql_blocks_write_operations(db_with_patient_table, operation, sql):
    """
    Validator should reject SQL with write operations (INSERT, UPDATE, DELETE).
    This test verifies that only SELECT and WITH queries are allowed.
    """
    state = _make_validator_state(sql)
    result = validate_sql(state, db_with_patient_table)
    validation = result["validation_result"]

    assert not validation.is_valid
    assert len(validation.syntax_errors) > 0


def test_validate_sql_allows_cte_queries(db_with_patient_table):
    """
    Validator should allow WITH (Common Table Expression) queries.
    CTEs are read-only and should be permitted.
    """
    state = _make_validator_state(
        "WITH tmp AS (SELECT id FROM ICSR.PATIENT WHERE id > 5) SELECT * FROM tmp"
    )

    result = validate_sql(state, db_with_patient_table)
    validation = result["validation_result"]

    assert validation.is_valid
    assert validation.sqlglot_parse_passed
    assert validation.explain_passed


def test_validate_sql_populates_validation_history(db_with_patient_table):
    """Validator should append result to validation_history."""
    state = _make_validator_state("SELECT * FROM ICSR.PATIENT")

    result = validate_sql(state, db_with_patient_table)

    assert "validation_history" in result
    assert len(result["validation_history"]) == 1
    assert result["validation_history"][0] is result["validation_result"]


def test_validate_sql_accumulates_validation_history(db_with_patient_table):
    """Multiple validations should accumulate in validation_history."""
    state = _make_validator_state("SELECT * FROM ICSR.PATIENT")

    # First validation
    result1 = validate_sql(state, db_with_patient_table)
    assert len(result1["validation_history"]) == 1

    # Simulate second validation (e.g., after repair) by passing history forward
    state2 = {
        **state,
        "validation_history": result1["validation_history"],
    }
    result2 = validate_sql(state2, db_with_patient_table)

    assert len(result2["validation_history"]) == 2
    assert result2["validation_history"][0] is result1["validation_result"]
    assert result2["validation_history"][1] is result2["validation_result"]


def test_validate_sql_preserves_errors_in_history(empty_db):
    """Validation errors should be preserved in validation_history entries."""
    state = _make_validator_state("SELECT * FROM NONEXISTENT_TABLE")

    result = validate_sql(state, empty_db)

    assert len(result["validation_history"]) == 1
    history_entry = result["validation_history"][0]
    assert not history_entry.is_valid
    assert len(history_entry.explain_errors) > 0
