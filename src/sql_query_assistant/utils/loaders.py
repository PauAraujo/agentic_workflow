import json
import logging

from pathlib import Path

from sql_query_assistant.config import Settings
from sql_query_assistant.domain import TableCard

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
        logger.info(
            "Loaded %d table cards from %d schema(s)",
            len(table_cards),
            len(schema_dirs),
        )

    return table_cards
