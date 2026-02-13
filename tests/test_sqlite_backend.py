import pytest
import sqlite3

from sql_query_assistant.database import create_backend
from sql_query_assistant.database.sqlite_backend import SQLiteBackend


def test_create_backend_returns_sqlite(dummy_settings):
    """Factory should return SQLiteBackend when db_type is sqlite."""
    backend = create_backend(dummy_settings)
    assert isinstance(backend, SQLiteBackend)


def test_create_backend_rejects_unsupported_type(dummy_settings):
    """Factory should raise ValueError for unsupported db_type."""
    dummy_settings.database.db_type = "postgres"
    with pytest.raises(ValueError, match="Unsupported DB_TYPE"):
        create_backend(dummy_settings)


def test_execute_query_returns_rows(db_with_patient_table):
    """execute_query should return rows, columns, and timing."""
    backend = SQLiteBackend(db_with_patient_table)
    rows, columns, time_ms = backend.execute_query(
        "SELECT * FROM ICSR.PATIENT ORDER BY id"
    )

    assert columns == ["id", "name"]
    assert len(rows) == 2
    assert rows[0] == {"id": 1, "name": "Alice"}
    assert rows[1] == {"id": 2, "name": "Bob"}
    assert time_ms >= 0


def test_execute_query_raises_on_bad_sql(db_with_patient_table):
    """execute_query should raise on invalid SQL."""
    backend = SQLiteBackend(db_with_patient_table)
    with pytest.raises(sqlite3.Error):
        backend.execute_query("SELECT * FROM NONEXISTENT_TABLE")


def test_validate_query_passes_valid_sql(db_with_patient_table):
    """validate_query should not raise for valid SQL."""
    backend = SQLiteBackend(db_with_patient_table)
    # Should not raise
    backend.validate_query("SELECT * FROM ICSR.PATIENT")


def test_validate_query_raises_on_bad_sql(db_with_patient_table):
    """validate_query should raise for SQL referencing missing tables."""
    backend = SQLiteBackend(db_with_patient_table)
    with pytest.raises(sqlite3.Error):
        backend.validate_query("SELECT * FROM NONEXISTENT_TABLE")
