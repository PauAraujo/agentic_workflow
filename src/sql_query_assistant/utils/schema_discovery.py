import logging

from sql_query_assistant.config import Settings
from sql_query_assistant.database import VALID_SCHEMA_NAME_PATTERN

logger = logging.getLogger(__name__)


def get_available_schemas(settings: Settings) -> dict[str, int]:
    """
    Discover available schemas from table_cards_dir.

    Scans subdirectories of table_cards_dir to find schemas with table cards.
    Each subdirectory name is a schema, and the count of .json files is the
    number of tables in that schema.

    Args:
        settings: Settings instance for path resolution

    Returns:
        Dict mapping schema_name -> table_count
    """
    schemas: dict[str, int] = {}

    table_cards_dir = settings.paths.table_cards_dir
    if not table_cards_dir.exists() or not table_cards_dir.is_dir():
        logger.warning("Table cards directory not found: %s", table_cards_dir)
        return schemas

    for schema_dir in table_cards_dir.iterdir():
        if not schema_dir.is_dir():
            continue

        schema_name = schema_dir.name

        # Skip invalid schema names (prevents issues with OData filters, SQL, etc.)
        if not VALID_SCHEMA_NAME_PATTERN.match(schema_name):
            logger.warning(
                "Skipping schema directory '%s': invalid name (must start with "
                "letter and contain only alphanumeric characters and underscores)",
                schema_name
            )
            continue

        table_count = len(list(schema_dir.glob("*.json")))
        if table_count > 0:
            schemas[schema_name] = table_count

    logger.debug("Discovered %d schemas: %s", len(schemas), list(schemas.keys()))
    return schemas
