import re
import logging
import sqlite3

from sql_query_assistant.config import Settings

logger = logging.getLogger(__name__)

# Valid schema name pattern: starts with letter, contains only alphanumeric and underscores
VALID_SCHEMA_NAME_PATTERN = re.compile(r'^[A-Za-z][A-Za-z0-9_]*$')


def _validate_schema_name(schema_name: str) -> None:
    """
    Validate that a schema name is safe to use in SQL statements.

    Schema names must start with a letter and contain only alphanumeric
    characters and underscores. This prevents SQL injection via malicious
    filenames.

    Args:
        schema_name: The schema name to validate

    Raises:
        ValueError: If schema name contains invalid characters
    """
    if not VALID_SCHEMA_NAME_PATTERN.match(schema_name):
        raise ValueError(
            f"Invalid schema name '{schema_name}'. Schema names must start with a letter "
            f"and contain only alphanumeric characters and underscores."
        )


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

        # Validate schema name to prevent SQL injection
        # SQLite doesn't support parameterized identifiers, so we must validate
        # before inserting into the SQL statement
        try:
            _validate_schema_name(schema_name)
        except ValueError as e:
            logger.error("Skipping database file %s: %s", db_file.name, e)
            continue

        # Schema name cannot be parameterized (it's an identifier, not a value)
        # We validate it above and then safely insert it into the SQL string
        # File path CAN be parameterized as it's a string value
        attach_sql = f"ATTACH DATABASE ? AS {schema_name}"
        cursor.execute(attach_sql, (str(db_file),))
        logger.debug("Attached schema '%s' from %s", schema_name, db_file.name)

    logger.info("Attached %d schemas from %s", len(db_files), db_dir)
