import re
import yaml
import json
import logging
import sqlite3

from copy import deepcopy
from pathlib import Path

from sql_query_assistant.config import Settings
from sql_query_assistant.domain import AssumptionCatalogEntry, TableCard
from sql_query_assistant.domain.input.table_card import Column

logger = logging.getLogger(__name__)


def load_table_cards(
    settings: Settings,
    base_path: Path | None = None,
    schemas: list[str] | None = None,
) -> list[TableCard]:
    """
    Load all table cards from schema subdirectories within the specified directory.

    Table cards are organized by schema: table_cards_dir/SCHEMA_NAME/*.json

    If base_path is not provided, uses the configured table_cards_dir.
    If schemas is not provided, loads from all schema subdirectories.
    Returns empty list if directory doesn't exist or contains no JSON files.

    Args:
        settings: Settings instance to use for path resolution.
        base_path: Path to the directory containing schema subdirectories.
                   If None, uses the default from PathSettings.
        schemas: List of schema names to load table cards from.
                 If None, discovers and loads from all schema subdirectories.

    Returns:
        list of validated TableCard models (empty if no files found)

    Raises:
        ValueError: If base_path exists but is not a directory, or if specified
                    schema subdirectory doesn't exist
        json.JSONDecodeError: If JSON files are malformed
        ValidationError: If table card data doesn't match schema
    """
    if base_path is None:
        base_path = settings.paths.table_cards_dir

    if not base_path.exists():
        logger.warning("Table cards directory not found: %s", base_path)
        return []

    if not base_path.is_dir():
        raise ValueError(f"Table cards path is not a directory: {base_path}")

    logger.info("Loading table cards from %s", base_path)

    # Discover schema subdirectories
    if schemas is None:
        # Auto-discover: all subdirectories are considered schemas
        schema_dirs = [d for d in base_path.iterdir() if d.is_dir()]
        if not schema_dirs:
            logger.warning("No schema subdirectories found in %s", base_path)
            return []
        schema_names = [dir.name for dir in schema_dirs]
        logger.info("Auto-discovered schemas: %s", ", ".join(schema_names))
    else:
        # Use specified schemas
        schema_dirs = [base_path / schema_name for schema_name in schemas]
        schema_names = schemas
        # Validate that all specified schema directories exist
        for schema_dir in schema_dirs:
            if not schema_dir.exists():
                raise ValueError(f"Schema directory not found: {schema_dir}")
            if not schema_dir.is_dir():
                raise ValueError(f"Schema path is not a directory: {schema_dir}")
        logger.info("Loading schemas: %s", ", ".join(schema_names))

    # Load table cards from all selected schema directories
    table_cards: list[TableCard] = []
    for schema_dir in schema_dirs:
        json_files = sorted(schema_dir.glob("*.json"))
        if not json_files:
            logger.warning("No JSON files found in schema directory: %s", schema_dir)
            continue

        for json_file in json_files:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            table_cards.append(TableCard.model_validate(data))

        logger.debug("Loaded %d table cards from %s", len(json_files), schema_dir.name)

    if not table_cards:
        logger.warning("No table cards loaded from any schema directory")
    else:
        logger.info("Loaded %d table cards from %d schema(s)", len(table_cards), len(schema_dirs))

    return table_cards


def load_assumption_catalog(
    settings: Settings,
    catalog_path: Path | None = None,
) -> list[AssumptionCatalogEntry]:
    """
    Load the assumptions catalog from YAML file.

    If catalog_path is not provided, uses the configured assumptions_catalog_file.

    Args:
        settings: Settings instance to use for path resolution.
        catalog_path: Path to the assumptions catalog YAML file.
                      If None, uses the default from PathSettings.

    Returns:
        Assumption catalog as a list of validated models

    Raises:
        FileNotFoundError: If the assumptions catalog file doesn't exist
        yaml.YAMLError: If YAML syntax is invalid
        ValueError: If catalog is not a list
        ValidationError: If entries don't match AssumptionCatalogEntry schema
    """
    if catalog_path is None:
        catalog_path = settings.paths.assumptions_catalog_file

    if not catalog_path.exists():
        raise FileNotFoundError(f"Assumptions catalog file not found: {catalog_path}")

    logger.info("Loading assumptions catalog from %s", catalog_path)

    raw_catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8")) or []

    if not isinstance(raw_catalog, list):
        raise ValueError(f"Assumptions catalog must be a list, got {type(raw_catalog).__name__}")

    catalog = [AssumptionCatalogEntry.model_validate(entry) for entry in raw_catalog]

    logger.info("Loaded %d assumptions", len(catalog))
    return catalog


def attach_all_schema_databases(cursor: sqlite3.Cursor, settings: Settings) -> None:
    """
    Auto-discover and attach all schema databases from the schemas_dir directory.

    Convention: Database filename (without .db extension) becomes the schema name.
    Example: ICSR.db → ATTACH DATABASE 'ICSR.db' AS ICSR

    This eliminates hardcoded schema mappings. To add a new schema, just add
    a new .db file named after the schema (e.g., ICSR_EMA.db, ICSR_LOOKUP.db).

    Args:
        cursor: SQLite cursor to execute ATTACH commands on
        settings: Settings instance for schemas_dir directory path

    Raises:
        sqlite3.Error: If ATTACH DATABASE command fails
    """
    db_dir = settings.paths.db_dir

    if not db_dir.exists():
        logger.warning("Database directory not found: %s", db_dir)
        return

    db_files = sorted(db_dir.glob("*.db"))

    if not db_files:
        logger.warning("No .db files found in %s", db_dir)
        return

    for db_file in db_files:
        schema_name = db_file.stem  # "ICSR.db" → "ICSR"
        cursor.execute("ATTACH DATABASE ? AS ?", (str(db_file), schema_name))
        logger.debug("Attached schema '%s' from %s", schema_name, db_file.name)

    logger.info("Attached %d schemas from %s", len(db_files), db_dir)


def map_oracle_type_to_sqlite(oracle_type: str) -> str:
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

    # Character/string types
    if oracle_type.startswith(("CHAR", "VARCHAR", "VARCHAR2", "NCHAR", "NVARCHAR", "NVARCHAR2", "CLOB", "NCLOB", "LONG")):
        return "TEXT"

    # Date/time types
    if oracle_type.startswith(("DATE", "TIMESTAMP")):
        return "TEXT"

    # Binary/blob types
    if oracle_type.startswith(("BLOB", "RAW", "LONG RAW", "VARBINARY", "BINARY")):
        return "BLOB"

    # Default fallback
    return "TEXT"


def transform_column_type(column: Column, source_dialect: str, target_dialect: str) -> Column:
    """
    Transforms a column's type from source dialect to target dialect.

    Args:
        column: Column object with type to transform
        source_dialect: Source database dialect (e.g., "oracle")
        target_dialect: Target database dialect (e.g., "sqlite")

    Returns:
        New Column object with transformed type
    """
    # Create a copy to avoid mutating the original
    new_column = deepcopy(column)

    # Only transform if source is Oracle and target is SQLite
    if source_dialect.lower() == "oracle" and target_dialect.lower() == "sqlite":
        new_column.type = map_oracle_type_to_sqlite(column.type)

    return new_column


def transform_table_card_types(
    table_cards: list[TableCard],
    source_dialect: str,
    target_dialect: str,
) -> list[TableCard]:
    """
    Transforms all column types in a list of table cards from source to target dialect.

    This function creates deep copies of the table cards to avoid mutating the originals.

    Args:
        table_cards: List of TableCard objects to transform
        source_dialect: Source database dialect (e.g., "oracle")
        target_dialect: Target database dialect (e.g., "sqlite")

    Returns:
        New list of TableCard objects with transformed column types
    """
    # Create deep copies to avoid mutating originals
    new_table_cards = []

    for table_card in table_cards:
        # Deep copy the table card
        new_table_card = deepcopy(table_card)

        # Transform each column's type
        new_table_card.columns = [
            transform_column_type(col, source_dialect, target_dialect)
            for col in table_card.columns
        ]

        new_table_cards.append(new_table_card)

    return new_table_cards
