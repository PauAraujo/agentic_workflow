import pytest
import sqlite3

from sql_query_assistant.modules.sql_validator.nodes import validate_sql
from sql_query_assistant.domain import SQLDraft, TableCard, TableMetadata


def _make_validator_state(sql, dialect="sqlite"):
    """Build a minimal workflow state for validator tests."""
    return {
        "sql_draft": SQLDraft(
            sql=sql,
            rationale="Test SQL",
            tables_used=["ICSR.PATIENT"],
            dialect=dialect,
        ),
    }


@pytest.fixture
def db_with_patient_table(dummy_settings):
    """Create a test database with PATIENT table using schema convention."""
    db_dir = dummy_settings.paths.db_dir
    db_dir.mkdir(parents=True, exist_ok=True)

    # Create ICSR.db following the schema naming convention
    icsr_db_path = db_dir / "ICSR.db"
    conn = sqlite3.connect(icsr_db_path)
    conn.execute("CREATE TABLE PATIENT (id INTEGER PRIMARY KEY, name TEXT)")
    conn.close()

    return dummy_settings


@pytest.fixture
def empty_db(dummy_settings):
    """Create an empty test database using schema convention."""
    db_dir = dummy_settings.paths.db_dir
    db_dir.mkdir(parents=True, exist_ok=True)

    # Create empty ICSR.db
    icsr_db_path = db_dir / "ICSR.db"
    sqlite3.connect(icsr_db_path).close()

    return dummy_settings


def test_validate_sql_passes_valid_query(db_with_patient_table):
    """Valid SQL should pass both SQLGlot parse and EXPLAIN validation."""
    state = _make_validator_state("SELECT id, name FROM ICSR.PATIENT WHERE id = 1")

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
    assert not validation.explain_passed    # but table doesn't exist
    assert len(validation.explain_errors) > 0


def test_validate_sql_uses_correct_dialect(db_with_patient_table):
    """Validator should use the dialect from sql_draft for parsing."""
    state = _make_validator_state(
        sql="SELECT * FROM ICSR.PATIENT LIMIT 5",
        dialect="sqlite"
    )

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
