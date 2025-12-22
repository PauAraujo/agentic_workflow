import logging
import sqlite3

from sql_query_assistant.config import Settings

logger = logging.getLogger(__name__)


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
