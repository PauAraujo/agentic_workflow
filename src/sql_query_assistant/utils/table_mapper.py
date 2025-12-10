import re

class TableMapper:
    """
    Table name mapping between SQLite (local twin) and Oracle (production).

    SQLite doesn't support schemas, so we use underscore naming: ICSR_PATIENT
    Oracle uses schema.table notation: ICSR.PATIENT
    """
    SQLITE_TO_ORACLE: dict[str, str] = {
        "ICSR_PATIENT": "ICSR.PATIENT",
    }
    ORACLE_TO_SQLITE: dict[str, str] = {
        oracle: sqlite for sqlite, oracle in SQLITE_TO_ORACLE.items()
    }
    # TODO: add dynamic table mapping to derive directly from table_metadata.name

    @classmethod
    def to_oracle(cls, sqlite_table: str) -> str:
        """
        Convert SQLite table name to Oracle schema.table format.

        Args:
            sqlite_table: SQLite table name (e.g., "ICSR_PATIENT")

        Returns:
            Oracle format (e.g., "ICSR.PATIENT")
        """
        return cls.SQLITE_TO_ORACLE.get(sqlite_table, sqlite_table)

    @classmethod
    def to_sqlite(cls, oracle_table: str) -> str:
        """
        Convert Oracle schema.table to SQLite table name.

        Args:
            oracle_table: Oracle table name (e.g., "ICSR.PATIENT")

        Returns:
            SQLite format (e.g., "ICSR_PATIENT")
        """
        return cls.ORACLE_TO_SQLITE.get(oracle_table, oracle_table)

    @classmethod
    def convert_sql_to_oracle(cls, sqlite_sql: str) -> str:
        """
        Convert SQL query from SQLite table names to Oracle format.

        Args:
            sqlite_sql: SQL with SQLite table names

        Returns:
            SQL with Oracle schema.table notation

        Example:
            TableMapper.convert_sql_to_oracle("SELECT * FROM ICSR_PATIENT")
            "SELECT * FROM ICSR.PATIENT"
        """
        oracle_sql = sqlite_sql
        for sqlite_name, oracle_name in cls.SQLITE_TO_ORACLE.items():
            # Use word boundaries to avoid partial matches
            pattern = r'\b' + re.escape(sqlite_name) + r'\b'
            oracle_sql = re.sub(pattern, oracle_name, oracle_sql, flags=re.IGNORECASE)
        return oracle_sql

    @classmethod
    def convert_sql_to_sqlite(cls, oracle_sql: str) -> str:
        """
        Convert SQL query from Oracle schema.table to SQLite format.

        Args:
            oracle_sql: SQL with Oracle schema.table notation

        Returns:
            SQL with SQLite table names

        Example:
            TableMapper.convert_sql_to_sqlite("SELECT * FROM ICSR.PATIENT")
            "SELECT * FROM ICSR_PATIENT"
        """
        sqlite_sql = oracle_sql
        for oracle_name, sqlite_name in cls.ORACLE_TO_SQLITE.items():
            # Use word boundaries to avoid partial matches
            pattern = r'\b' + re.escape(oracle_name) + r'\b'
            sqlite_sql = re.sub(pattern, sqlite_name, sqlite_sql, flags=re.IGNORECASE)
        return sqlite_sql
