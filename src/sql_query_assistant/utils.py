import yaml
import json
import logging
import sqlite3

from pathlib import Path

from sql_query_assistant.config import Settings
from sql_query_assistant.domain import AssumptionCatalogEntry, TableCard

logger = logging.getLogger(__name__)


def load_table_cards(
    settings: Settings,
    base_path: Path | None = None,
) -> list[TableCard]:
    """
    Load all table cards from the specified directory.

    If base_path is not provided, uses the configured table_cards_dir.
    Returns empty list if directory doesn't exist or contains no JSON files.

    Args:
        settings: Settings instance to use for path resolution.
        base_path: Path to the directory containing table card JSON files.
                   If None, uses the default from PathSettings.

    Returns:
        list of validated TableCard models (empty if no files found)

    Raises:
        ValueError: If base_path exists but is not a directory
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

    table_cards: list[TableCard] = []
    json_files = sorted(base_path.glob("*.json"))

    if not json_files:
        logger.warning("No JSON files found in %s", base_path)
        return table_cards

    for json_file in json_files:
        data = json.loads(json_file.read_text(encoding="utf-8"))
        table_cards.append(TableCard.model_validate(data))

    logger.info("Loaded %d table cards", len(table_cards))
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
    Auto-discover and attach all schema databases from the db directory.

    Convention: Database filename (without .db extension) becomes the schema name.
    Example: ICSR.db → ATTACH DATABASE 'ICSR.db' AS ICSR

    This eliminates hardcoded schema mappings. To add a new schema, just add
    a new .db file named after the schema (e.g., ICSR_EMA.db, ICSR_LOOKUP.db).

    Args:
        cursor: SQLite cursor to execute ATTACH commands on
        settings: Settings instance for db directory path

    Raises:
        sqlite3.Error: If ATTACH DATABASE command fails
    """
    db_dir = settings.paths.input_dir / settings.paths.db_subdir

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
