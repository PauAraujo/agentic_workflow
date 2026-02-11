import re

from sql_query_assistant.domain import Column, TableCard


def _map_oracle_type_to_sqlite(oracle_type: str) -> str:
    """
    Maps Oracle type strings to SQLite affinities.

    SQLite has 5 storage classes: NULL, INTEGER, REAL, TEXT, BLOB.
    This uses simple string parsing to map Oracle types to SQLite affinities.

    Args:
        oracle_type: Oracle type string (e.g., "NUMBER(10,0)", "VARCHAR2(100)")

    Returns:
        SQLite affinity string: INTEGER, REAL, TEXT, or BLOB
    """

    oracle_type = oracle_type.strip().upper()

    # Handle NUMBER type with precision and scale
    number_match = re.match(r"NUMBER\((\d+)(?:,\s*(\d+))?\)", oracle_type)
    if number_match:
        scale = number_match.group(2)
        if scale is None or int(scale) == 0:
            return "INTEGER"
        return "REAL"

    # Handle NUMBER without parameters (floating point)
    if oracle_type == "NUMBER":
        return "REAL"

    # Handle DECIMAL/NUMERIC types
    decimal_match = re.match(r"(?:DECIMAL|NUMERIC)\((\d+)(?:,\s*(\d+))?\)", oracle_type)
    if decimal_match:
        scale = decimal_match.group(2)
        if scale is None or int(scale) == 0:
            return "INTEGER"
        return "REAL"

    # Integer types
    if oracle_type.startswith(("INTEGER", "INT", "SMALLINT", "TINYINT", "BIGINT")):
        return "INTEGER"

    # Floating point types
    if oracle_type.startswith(("FLOAT", "DOUBLE", "REAL", "BINARY_FLOAT", "BINARY_DOUBLE")):
        return "REAL"

    # Binary/blob types (check LONG RAW before LONG to avoid mismatching)
    if oracle_type.startswith(("BLOB", "LONG RAW", "RAW", "VARBINARY", "BINARY")):
        return "BLOB"

    # Character/string types (LONG checked after LONG RAW)
    if oracle_type.startswith(("CHAR", "VARCHAR", "VARCHAR2", "NCHAR", "NVARCHAR", "NVARCHAR2", "CLOB", "NCLOB", "LONG")):
        return "TEXT"

    # Date/time types
    if oracle_type.startswith(("DATE", "TIMESTAMP")):
        return "TEXT"

    # Default fallback
    return "TEXT"


def _transform_column_type(column: Column, source_dialect: str, target_dialect: str) -> Column:
    """
    Transforms a column's type from source dialect to target dialect.

    Args:
        column: Column object with type to transform
        source_dialect: Source database dialect (e.g., "oracle")
        target_dialect: Target database dialect (e.g., "sqlite")

    Returns:
        New Column object with transformed type
    """
    if source_dialect.lower() == "oracle" and target_dialect.lower() == "sqlite":
        new_type = _map_oracle_type_to_sqlite(column.type)
        return column.model_copy(update={"type": new_type})

    return column


def transform_column_types(
    table_cards: list[TableCard],
    source_dialect: str,
    target_dialect: str,
) -> list[TableCard]:
    """
    Transforms types in a list of table cards from source to target dialect.

    Args:
        table_cards: List of TableCard objects to transform
        source_dialect: Source database dialect (e.g., "oracle")
        target_dialect: Target database dialect (e.g., "sqlite")

    Returns:
        New list of TableCard objects with transformed column types
    """
    new_table_cards = []

    for table_card in table_cards:
        transformed_columns = [
            _transform_column_type(col, source_dialect, target_dialect)
            for col in table_card.columns
        ]

        # Create new TableCard with transformed columns
        new_table_card = table_card.model_copy(update={"columns": transformed_columns})
        new_table_cards.append(new_table_card)

    return new_table_cards
