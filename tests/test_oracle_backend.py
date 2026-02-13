import os
import pytest

from sql_query_assistant.config import DatabaseSettings

# Skip all tests in this module unless Oracle credentials are available
pytestmark = pytest.mark.oracle


def _oracle_credentials_available() -> bool:
    """Check if Oracle credentials are set in environment."""
    return all(
        os.getenv(var) for var in ["DB_HOST", "DB_SERVICE", "DB_USER", "DB_PASSWORD"]
    )


@pytest.fixture
def oracle_settings(dummy_settings):
    """Create settings configured for Oracle backend."""
    if not _oracle_credentials_available():
        pytest.skip("Oracle credentials not available")

    dummy_settings.database = DatabaseSettings(
        db_type="oracle",
        oracle_host=os.getenv("DB_HOST"),
        oracle_port=int(os.getenv("DB_PORT", "1521")),
        oracle_service=os.getenv("DB_SERVICE"),
        oracle_user=os.getenv("DB_USER"),
        oracle_password=os.getenv("DB_PASSWORD"),
    )
    return dummy_settings


def test_oracle_database_settings_validates_credentials():
    """DatabaseSettings should reject oracle mode without credentials."""
    # _env_file=None prevents loading from .env (which may have real Oracle credentials)
    with pytest.raises(ValueError, match="Oracle credentials required"):
        DatabaseSettings(db_type="oracle", _env_file=None)


def test_oracle_database_settings_accepts_valid_credentials():
    """DatabaseSettings should accept oracle mode with all credentials."""
    settings = DatabaseSettings(
        db_type="oracle",
        oracle_host="localhost",
        oracle_service="ORCL",
        oracle_user="user",
        oracle_password="pass",
        _env_file=None,
    )
    assert settings.db_type == "oracle"
    assert settings.oracle_host == "localhost"


def test_oracle_execute_query(oracle_settings):
    """Oracle backend should execute a simple query."""
    from sql_query_assistant.database.oracle_backend import OracleBackend

    backend = OracleBackend(oracle_settings)
    rows, columns, time_ms = backend.execute_query("SELECT 1 AS test_col FROM DUAL")

    assert len(rows) == 1
    assert "TEST_COL" in columns
    assert time_ms >= 0


def test_oracle_validate_query(oracle_settings):
    """Oracle backend should validate a query without error."""
    from sql_query_assistant.database.oracle_backend import OracleBackend

    backend = OracleBackend(oracle_settings)
    # Should not raise
    backend.validate_query("SELECT 1 FROM DUAL")
