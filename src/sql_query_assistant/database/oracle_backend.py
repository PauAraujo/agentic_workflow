import time
import logging
import oracledb

from sql_query_assistant.config import Settings

logger = logging.getLogger(__name__)


class OracleBackend:
    """
    Oracle database backend using oracledb thin client.
    """
    def __init__(self, settings: Settings):
        self._settings = settings

    def _connect(self) -> oracledb.Connection:
        """Create a new Oracle connection from settings."""
        db_settings = self._settings.database
        # Construct the dsn connection string
        data_source_name = oracledb.makedsn(
            db_settings.oracle_host,
            db_settings.oracle_port,
            service_name=db_settings.oracle_service,
        )
        conn = oracledb.connect(
            user=db_settings.oracle_user,
            password=db_settings.oracle_password,
            dsn=data_source_name,
        )
        logger.debug("Connected to Oracle at %s:%d/%s", db_settings.oracle_host, db_settings.oracle_port, db_settings.oracle_service)
        return conn

    def execute_query(self, sql: str) -> tuple[list[dict], list[str], float]:
        """
        Execute a SQL query against the Oracle database.

        Args:
            sql: The SQL query to execute

        Returns:
            Tuple of (rows as list of dicts, column_names, execution_time_ms)

        Raises:
            oracledb.Error: If query execution fails
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()

            cursor.execute("SET TRANSACTION READ ONLY")

            start_time = time.perf_counter()
            cursor.execute(sql)
            execution_time_ms = (time.perf_counter() - start_time) * 1000

            column_names = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
            result_rows = [dict(zip(column_names, row)) for row in rows]

            logger.debug("Oracle query returned %d rows in %.2fms", len(result_rows), execution_time_ms)
            return result_rows, column_names, execution_time_ms
        finally:
            conn.close()

    def validate_query(self, sql: str) -> None:
        """
        Validate a SQL query using DBMS_SQL.PARSE (read-only dry-run against Oracle schema).

        DBMS_SQL.PARSE performs full parsing including syntax checking, object name
        resolution, and privilege verification without writing anything (unlike
        EXPLAIN PLAN FOR, which inserts into PLAN_TABLE).

        Args:
            sql: The SQL query to validate

        Raises:
            oracledb.Error: If the query is invalid (syntax, missing objects, etc.)
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            # This only parses the SQL; it does not execute DML statements
            cursor.execute(
                """
                DECLARE
                    c INTEGER := DBMS_SQL.OPEN_CURSOR;
                BEGIN
                    DBMS_SQL.PARSE(c, :sql_text, DBMS_SQL.NATIVE);
                    DBMS_SQL.CLOSE_CURSOR(c);
                EXCEPTION
                    WHEN OTHERS THEN
                        DBMS_SQL.CLOSE_CURSOR(c);
                        RAISE;
                END;
                """,
                sql_text=sql,
            )
            logger.debug("Oracle DBMS_SQL.PARSE validation passed")
        finally:
            conn.close()
