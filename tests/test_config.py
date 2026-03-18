import pytest

from sql_query_assistant.config import (
    AgentSettings,
    AzureOpenAISettings,
    DatabaseSettings,
    DrafterModelConfig,
    RepairerModelConfig,
    TableSelectorModelConfig,
    PathSettings,
    Settings,
)


@pytest.fixture
def _clear_agent_env(monkeypatch):
    """Remove all agent override env vars so tests start from a known baseline."""
    for agent in ("DRAFTER", "REPAIRER", "TABLE_SELECTOR"):
        for suffix in ("MODEL_PROVIDER", "MODEL_NAME", "TEMPERATURE"):
            monkeypatch.delenv(f"{agent}_{suffix}", raising=False)


def _make_settings(tmp_path) -> Settings:
    """Create a Settings instance isolated from .env file."""
    return Settings(
        azure=AzureOpenAISettings(
            endpoint="https://example.openai.azure.com",
            api_key="dummy-key",
            api_version="2024-02-15-preview",
            max_retries=1,
            _env_file=None,
        ),
        langfuse=None,
        database=DatabaseSettings(type="sqlite", _env_file=None),
        paths=PathSettings(input_dir=tmp_path, output_dir=tmp_path),
        agents=AgentSettings(
            drafter=DrafterModelConfig(_env_file=None),
            repairer=RepairerModelConfig(_env_file=None),
            table_selector=TableSelectorModelConfig(_env_file=None),
        ),
        _env_file=None,
    )


def test_env_vars_override_defaults(_clear_agent_env, tmp_path, monkeypatch):
    """Real env vars should replace the hardcoded defaults."""
    monkeypatch.setenv("DRAFTER_MODEL_PROVIDER", "aws")
    monkeypatch.setenv("DRAFTER_MODEL_NAME", "claude")
    monkeypatch.setenv("AWS_PROFILE", "test")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    settings = _make_settings(tmp_path)

    assert settings.agents.drafter.model_provider == "aws"
    assert settings.agents.drafter.model_name == "claude"


def test_temperature_from_env(_clear_agent_env, tmp_path, monkeypatch):
    """Temperature can be overridden via env var."""
    monkeypatch.setenv("REPAIRER_TEMPERATURE", "0.5")

    settings = _make_settings(tmp_path)

    assert settings.agents.repairer.temperature == 0.5


def test_partial_override(_clear_agent_env, tmp_path, monkeypatch):
    """Setting only one field should merge with existing defaults, not replace them."""
    monkeypatch.setenv("DRAFTER_MODEL_NAME", "custom-model")

    settings = _make_settings(tmp_path)

    assert settings.agents.drafter.model_name == "custom-model"
    assert settings.agents.drafter.model_provider == "azure"
