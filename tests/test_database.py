import pytest
import sqlite3

from sql_query_assistant.database.sqlite_backend import SQLiteBackend
from sql_query_assistant.database import validate_schema_name


@pytest.mark.parametrize(
    "schema_name",
    [
        "ICSR",
        "ICSR_EMA",
        "ICSR_LOOKUP",
        "Schema1",
        "my_schema",
        "MySchema123",
        "A",
        "a1_b2_c3",
    ],
)
def test_validate_schema_name_accepts_valid_names(schema_name):
    """Valid schema names should pass validation."""
    # Should not raise
    validate_schema_name(schema_name)


@pytest.mark.parametrize(
    "schema_name,reason",
    [
        ("123invalid", "starts with number"),
        ("_invalid", "starts with underscore"),
        ("invalid-name", "contains hyphen"),
        ("", "empty string"),
        ("invalid\nname", "newline"),
        ("invalid\0name", "null byte"),
        ("invalid.name", "contains dot"),
    ],
)
def test_validate_schema_name_rejects_invalid_names(schema_name, reason):
    """Invalid schema names should raise ValueError."""
    with pytest.raises(ValueError, match="Invalid schema name"):
        validate_schema_name(schema_name)


def test_attach_all_schema_databases_with_valid_schemas(tmp_path, dummy_settings):
    """Successfully attach databases with valid schema names."""
    # Create schemas subdirectory (db_dir is a property: input_dir / schemas_dir)
    db_dir = tmp_path / dummy_settings.paths.schemas_dir
    db_dir.mkdir(parents=True)

    # Create valid database files
    (db_dir / "ICSR.db").touch()
    (db_dir / "ICSR_LOOKUP.db").touch()

    # Attach databases via backend
    backend = SQLiteBackend(dummy_settings)
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    backend._attach_all_schema_databases(cursor)

    # Verify schemas are attached
    cursor.execute("PRAGMA database_list")
    databases = cursor.fetchall()

    # Should have main + 2 attached schemas
    assert len(databases) == 3

    # Extract schema names (databases is list of tuples: (seq, name, file))
    schema_names = [db[1] for db in databases]
    assert "ICSR" in schema_names
    assert "ICSR_LOOKUP" in schema_names

    conn.close()


def test_attach_all_schema_databases_validates_schema_names(
    tmp_path, dummy_settings, caplog
):
    """Skip database files with invalid schema names and log errors."""
    # Create schemas subdirectory
    db_dir = tmp_path / dummy_settings.paths.schemas_dir
    db_dir.mkdir(parents=True)

    # Create one valid and multiple invalid database files
    (db_dir / "VALID_SCHEMA.db").touch()

    # Invalid schema names covering various attack vectors and invalid patterns
    invalid_files = [
        "invalid-name.db",  # contains hyphen
        "drop;table.db",  # SQL injection attempt with semicolon
        "schema.subtable.db",  # contains dot (could confuse schema.table syntax)
    ]
    for filename in invalid_files:
        (db_dir / filename).touch()

    # Attach databases via backend
    backend = SQLiteBackend(dummy_settings)
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    backend._attach_all_schema_databases(cursor)

    # Verify only valid schema is attached
    cursor.execute("PRAGMA database_list")
    databases = cursor.fetchall()

    # Should have main + 1 valid schema
    assert len(databases) == 2

    schema_names = [db[1] for db in databases]
    assert "VALID_SCHEMA" in schema_names

    # Verify none of the invalid schema names were attached
    for filename in invalid_files:
        schema_name = filename.replace(".db", "")
        assert schema_name not in schema_names

    # Verify error messages were logged for all invalid files
    assert "Skipping database file" in caplog.text
    assert "Invalid schema name" in caplog.text

    conn.close()


def test_attach_all_schema_databases_handles_missing_directory(dummy_settings, caplog):
    """Handle missing database directory gracefully."""
    # Don't create the schemas directory - it won't exist
    # db_dir should be: tmp_path / schemas_dir, but we don't create it

    backend = SQLiteBackend(dummy_settings)
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    # Should not raise, just log warning
    backend._attach_all_schema_databases(cursor)

    # Verify warning was logged
    assert "Database directory not found" in caplog.text

    # Only main database should exist
    cursor.execute("PRAGMA database_list")
    databases = cursor.fetchall()
    assert len(databases) == 1

    conn.close()


def test_attach_all_schema_databases_handles_empty_directory(
    tmp_path, dummy_settings, caplog
):
    """Handle empty database directory gracefully."""
    # Create empty schemas directory
    db_dir = tmp_path / dummy_settings.paths.schemas_dir
    db_dir.mkdir(parents=True)

    backend = SQLiteBackend(dummy_settings)
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    # Should not raise, just log warning
    backend._attach_all_schema_databases(cursor)

    # Verify warning was logged
    assert "No .db files found" in caplog.text

    # Only main database should exist
    cursor.execute("PRAGMA database_list")
    databases = cursor.fetchall()
    assert len(databases) == 1

    conn.close()
