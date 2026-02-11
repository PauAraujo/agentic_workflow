import time
import logging
import sqlite3

from sql_query_assistant.config import Settings
from sql_query_assistant.database import validate_schema_name

logger = logging.getLogger(__name__)


class SQLiteBackend:
    """
    SQLite database backend using in-memory connections with attached schema databases.

    Each method creates a fresh connection, attaches all schema .db files from
    settings.paths.db_dir, runs the operation, and closes the connection.
    """

    def __init__(self, settings: Settings):
        self._settings = settings

    def _attach_all_schema_databases(self, cursor: sqlite3.Cursor) -> None:
        """
        Auto-discover and attach all schema databases from the schemas_dir directory.

        Convention: Database filename (without .db extension) becomes the schema name.
        Example: ICSR.db -> ATTACH DATABASE 'ICSR.db' AS ICSR
        """
        db_dir = self._settings.paths.db_dir

        if not db_dir.exists():
            logger.warning("Database directory not found: %s", db_dir)
            return

        db_files = sorted(db_dir.glob("*.db"))

        if not db_files:
            logger.warning("No .db files found in %s", db_dir)
            return

        attached_count = 0
        for db_file in db_files:
            schema_name = db_file.stem  # "ICSR.db" -> "ICSR"

            try:
                validate_schema_name(schema_name)
            except ValueError as e:
                logger.error("Skipping database file %s: %s", db_file.name, e)
                continue

            # Schema name cannot be parameterized (it's an identifier, not a value)
            # We validate it above and then safely insert it into the SQL string
            # File path CAN be parameterized as it's a string value
            attach_sql = f"ATTACH DATABASE ? AS {schema_name}"
            cursor.execute(attach_sql, (str(db_file),))
            attached_count += 1
            logger.debug("Attached schema '%s' from %s", schema_name, db_file.name)

        logger.info("Attached %d schemas from %s", attached_count, db_dir)

    def execute_query(self, sql: str) -> tuple[list[dict], list[str], float]:
        """
        Execute a SQL query against in-memory SQLite with attached schemas.

        Args:
            sql: The SQL query to execute

        Returns:
            Tuple of (rows as list of dicts, column_names, execution_time_ms)

        Raises:
            sqlite3.Error: If query execution fails
        """
        with sqlite3.connect(":memory:") as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            self._attach_all_schema_databases(cursor)

            # enforce read-only
            cursor.execute("PRAGMA query_only = ON")

            start_time = time.perf_counter()
            cursor.execute(sql)
            execution_time_ms = (time.perf_counter() - start_time) * 1000

            rows = cursor.fetchall()
            column_names = [desc[0] for desc in cursor.description] if cursor.description else []
            result_rows = [dict(row) for row in rows]

        return result_rows, column_names, execution_time_ms

    def validate_query(self, sql: str) -> None:
        """
        Validate a SQL query using EXPLAIN QUERY PLAN (dry-run against actual schema).

        Enforces read-only mode as defense-in-depth.

        Args:
            sql: The SQL query to validate

        Raises:
            sqlite3.Error: If the query is invalid (schema errors, etc.)
        """
        with sqlite3.connect(":memory:") as conn:
            cursor = conn.cursor()

            self._attach_all_schema_databases(cursor)

            # enforce read-only (defense-in-depth)
            cursor.execute("PRAGMA query_only = ON")

            explain_sql = f"EXPLAIN QUERY PLAN {sql}"
            cursor.execute(explain_sql)
