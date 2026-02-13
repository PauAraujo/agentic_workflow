import re

from typing import Protocol

from sql_query_assistant.config import Settings


class DatabaseBackend(Protocol):
    """
    Structural type contract for database backends.

    Any class that implements execute_query and validate_query with
    matching signatures satisfies this protocol.
    """

    def execute_query(self, sql: str) -> tuple[list[dict], list[str], float]:
        """Execute a SQL query and return (rows, column_names, execution_time_ms)."""
        ...

    def validate_query(self, sql: str) -> None:
        """Dry-run a SQL query to check for syntax/schema errors."""
        ...


# Valid schema name pattern: starts with letter, contains only alphanumeric and underscores
VALID_SCHEMA_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def validate_schema_name(schema_name: str) -> None:
    """
    Validate that a schema name is safe to use in SQL identifiers and OData filters.

    Schema names must start with a letter and contain only alphanumeric
    characters and underscores. This prevents injection via malicious
    filenames or untrusted CLI input.

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


def create_backend(settings: Settings) -> DatabaseBackend:
    """
    Factory function that returns the appropriate database backend.

    Args:
        settings: Application settings containing database configuration

    Returns:
        A DatabaseBackend-compatible instance (SQLiteBackend or OracleBackend)

    Raises:
        ValueError: If db_type is not supported
    """
    db_type = settings.database.db_type

    if db_type == "sqlite":
        from .sqlite_backend import SQLiteBackend

        return SQLiteBackend(settings)
    elif db_type == "oracle":
        from .oracle_backend import OracleBackend

        return OracleBackend(settings)
    else:
        raise ValueError(f"Unsupported DB_TYPE: {db_type}")
