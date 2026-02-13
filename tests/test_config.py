import pytest
from unittest.mock import patch

from sql_query_assistant.config import (
    AzureOpenAISettings,
    DatabaseSettings,
    PathSettings,
    Settings,
)


@pytest.fixture
def _clear_agent_env(monkeypatch):
    """
    Remove all agent override env vars so tests start from a known baseline.

    Without this, env vars from the host machine (or earlier tests) could
    silently change agent configs and cause false passes/failures.
    """
    for agent in ("DRAFTER", "REPAIRER", "TABLE_SELECTOR"):
        for suffix in ("MODEL_PROVIDER", "MODEL_NAME", "TEMPERATURE"):
            monkeypatch.delenv(f"{agent}_{suffix}", raising=False)


@pytest.fixture
def clean_settings(_clear_agent_env, tmp_path):
    """
    Create a Settings instance with all defaults and no external influence.

    Depends on _clear_agent_env to wipe agent env vars, and patches out the
    .env file so only values explicitly set in each test are visible.
    """
    with patch("sql_query_assistant.config._dotenv_values", {}):  # ignore .env file
        return Settings(
            azure=AzureOpenAISettings(
                openai_endpoint="https://example.openai.azure.com",
                api_key="dummy-key",
                api_version="2024-02-15-preview",
                max_retries=1,
            ),
            langfuse=None,  # disable tracing
            database=DatabaseSettings(db_type="sqlite"),
            paths=PathSettings(input_dir=tmp_path, output_dir=tmp_path),
        )


def test_env_vars_override_defaults(clean_settings, monkeypatch):
    """Real env vars should replace the hardcoded defaults in AgentSettings."""
    monkeypatch.setenv("DRAFTER_MODEL_PROVIDER", "aws")  # default is "azure"
    monkeypatch.setenv("DRAFTER_MODEL_NAME", "claude")  # default is "gpt-4o-mini"

    with patch("sql_query_assistant.config._dotenv_values", {}):
        settings = clean_settings.parse_agent_configs_from_env()

    assert settings.agents.drafter.provider == "aws"  # overridden
    assert settings.agents.drafter.model_name == "claude"  # overridden


def test_dotenv_file_is_read(clean_settings, monkeypatch):
    """Values in the .env file should be picked up when no real env var is set."""
    monkeypatch.delenv("REPAIRER_TEMPERATURE", raising=False)
    fake_dotenv = {"REPAIRER_TEMPERATURE": "0.5"}

    with patch("sql_query_assistant.config._dotenv_values", fake_dotenv):
        settings = clean_settings.parse_agent_configs_from_env()

    assert settings.agents.repairer.temperature == 0.5


def test_real_env_takes_precedence_over_dotenv(clean_settings, monkeypatch):
    """When both a real env var and a .env entry exist for the same key, the real env var wins."""
    monkeypatch.setenv("DRAFTER_MODEL_NAME", "from-env")  # real environment
    fake_dotenv = {"DRAFTER_MODEL_NAME": "from-dotenv"}  # .env file

    with patch("sql_query_assistant.config._dotenv_values", fake_dotenv):
        settings = clean_settings.parse_agent_configs_from_env()

    assert settings.agents.drafter.model_name == "from-env"  # real env takes priority


def test_blank_values_are_ignored(clean_settings, monkeypatch):
    """Whitespace-only env vars should be treated as unset, not passed as empty strings."""
    monkeypatch.setenv("DRAFTER_MODEL_PROVIDER", "   ")  # treated as unset

    with patch("sql_query_assistant.config._dotenv_values", {}):
        settings = clean_settings.parse_agent_configs_from_env()

    assert settings.agents.drafter.provider == "azure"  # default preserved, blank ignored


def test_partial_override(clean_settings, monkeypatch):
    """Setting only one field should merge with existing defaults, not replace them."""
    monkeypatch.setenv("DRAFTER_MODEL_NAME", "custom-model")

    with patch("sql_query_assistant.config._dotenv_values", {}):
        settings = clean_settings.parse_agent_configs_from_env()

    assert settings.agents.drafter.model_name == "custom-model"  # overridden
    assert settings.agents.drafter.provider == "azure"  # kept from default
