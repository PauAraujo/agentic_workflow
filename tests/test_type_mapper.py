import pytest

from sql_query_assistant.domain.table_card import Column, TableCard, TableMetadata
from sql_query_assistant.utils import transform_column_types
from sql_query_assistant.utils.type_mapper import (
    _map_oracle_type_to_sqlite,
    _transform_column_type,
)

ORACLE = "oracle"
SQLITE = "sqlite"
POSTGRESQL = "postgresql"


@pytest.fixture
def sample_column():
    """
    Create a sample column for testing.

    Returns:
        Column: A Column instance with Oracle NUMBER type.
    """

    return Column(name="ID", type="NUMBER(15,0)", description="Primary key")


@pytest.fixture
def sample_table_card():
    """Create a sample table card for testing."""
    return TableCard(
        table_metadata=TableMetadata(
            qualified_name="ICSR.PATIENT",
            schema_name="ICSR",
            name="PATIENT",
            description="Patient data",
        ),
        columns=[
            Column(name="ID", type="NUMBER(15,0)", description="Primary key"),
            Column(name="NAME", type="VARCHAR2(100)", description="Patient name"),
            Column(name="BIRTH_DATE", type="DATE", description="Birth date"),
        ],
    )


# _map_oracle_type_to_sqlite tests
@pytest.mark.parametrize(
    "oracle_type,expected_sqlite_type",
    [
        # NUMBER types
        ("NUMBER(15,0)", "INTEGER"),
        ("NUMBER(10,2)", "REAL"),
        ("NUMBER(15)", "INTEGER"),
        ("NUMBER", "REAL"),
        # Character types
        ("VARCHAR2(100)", "TEXT"),
        ("CHAR(10)", "TEXT"),
        ("CLOB", "TEXT"),
        ("LONG", "TEXT"),
        # Date/Time types
        ("DATE", "TEXT"),
        ("TIMESTAMP(6)", "TEXT"),
        # Binary types
        ("BLOB", "BLOB"),
        ("LONG RAW", "BLOB"),
        # Floating point types
        ("FLOAT", "REAL"),
        ("BINARY_DOUBLE", "REAL"),
        # Integer types
        ("INTEGER", "INTEGER"),
        ("SMALLINT", "INTEGER"),
    ],
)
def test_oracle_to_sqlite_type_mapping(oracle_type, expected_sqlite_type):
    """Test that Oracle types are correctly mapped to SQLite types."""
    assert _map_oracle_type_to_sqlite(oracle_type) == expected_sqlite_type


@pytest.mark.parametrize(
    "oracle_type,expected",
    [
        ("varchar2(100)", "TEXT"),
        ("VARCHAR2(100)", "TEXT"),
        ("  VARCHAR2(60)  ", "TEXT"),
    ],
)
def test_oracle_mapping_case_and_whitespace(oracle_type, expected):
    """Test that type mapping handles case insensitivity and whitespace."""
    assert _map_oracle_type_to_sqlite(oracle_type) == expected


def test_unknown_type_defaults_to_text():
    """Test that unknown types default to TEXT."""
    assert _map_oracle_type_to_sqlite("SOME_UNKNOWN_TYPE") == "TEXT"


# _transform_column_type tests
def test_transform_column_type_oracle_to_sqlite(sample_column):
    """Test that column type is transformed from Oracle to SQLite."""
    transformed = _transform_column_type(sample_column, ORACLE, SQLITE)
    assert transformed.type == "INTEGER"
    assert transformed.name == "ID"
    assert transformed.description == "Primary key"


def test_transform_column_does_not_mutate_original(sample_column):
    """Test that the original column is not mutated."""
    original_type = sample_column.type
    transformed = _transform_column_type(sample_column, ORACLE, SQLITE)

    assert sample_column.type == original_type
    assert transformed.type == "INTEGER"


@pytest.mark.parametrize(
    "source_db,target_db",
    [
        (POSTGRESQL, SQLITE),  # Non-Oracle source
        (ORACLE, POSTGRESQL),  # Non-SQLite target
    ],
)
def test_transform_column_only_for_oracle_to_sqlite(
    sample_column, source_db, target_db
):
    """Test that transformation only occurs for Oracle → SQLite."""
    result = _transform_column_type(sample_column, source_db, target_db)
    assert result.type == "NUMBER(15,0)"  # Unchanged


# transform_column_types tests
def test_transform_table_card_all_columns(sample_table_card):
    """Test that all columns in a table card are transformed."""
    transformed = transform_column_types([sample_table_card], ORACLE, SQLITE)

    assert len(transformed) == 1
    assert transformed[0].columns[0].type == "INTEGER"
    assert transformed[0].columns[1].type == "TEXT"
    assert transformed[0].columns[2].type == "TEXT"


def test_transform_multiple_table_cards():
    """Test that multiple table cards are all transformed."""
    table_cards = [
        TableCard(
            table_metadata=TableMetadata(
                qualified_name="ICSR.TABLE1",
                schema_name="ICSR",
                name="TABLE1",
                description="Table 1",
            ),
            columns=[Column(name="COL1", type="NUMBER(15,0)", description="Col 1")],
        ),
        TableCard(
            table_metadata=TableMetadata(
                qualified_name="ICSR.TABLE2",
                schema_name="ICSR",
                name="TABLE2",
                description="Table 2",
            ),
            columns=[Column(name="COL2", type="VARCHAR2(100)", description="Col 2")],
        ),
    ]

    transformed = transform_column_types(table_cards, ORACLE, SQLITE)

    assert len(transformed) == 2
    assert transformed[0].columns[0].type == "INTEGER"
    assert transformed[1].columns[0].type == "TEXT"


def test_transform_table_card_does_not_mutate_original(sample_table_card):
    """Test that original table cards are not mutated."""
    original_type = sample_table_card.columns[0].type

    transformed = transform_column_types([sample_table_card], ORACLE, SQLITE)

    assert sample_table_card.columns[0].type == original_type
    assert transformed[0].columns[0].type == "INTEGER"


def test_transform_handles_empty_list():
    """Test that empty list is handled correctly."""
    result = transform_column_types([], ORACLE, SQLITE)
    assert result == []
