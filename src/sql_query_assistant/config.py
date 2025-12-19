import os

from pathlib import Path
from typing import Literal
from pydantic import (
    AliasChoices,
    AnyHttpUrl,
    BaseModel,
    Field,
    ValidationError,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_project_root() -> Path:
    """Find project root by locating pyproject.toml."""
    current = Path(__file__).resolve()
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    # Fallback to three levels up if no marker found
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = _find_project_root()

class PathSettings(BaseModel):
    """
    Paths to input files and artifacts used by the workflow.

    The base fields can be overridden via environment settings, while
    the derived properties keep call sites simple and consistent.
    """
    input_dir: Path = PROJECT_ROOT / "input"
    output_dir: Path = PROJECT_ROOT / "output"
    table_cards_subdir: str = "table_cards"
    assumptions_catalog_subdir: str = "assumptions_catalog"
    assumptions_catalog_filename: str = "assumptions_catalog.yaml"
    query_runs_filename: str = "query_runs.csv"
    query_assumptions_filename: str = "query_assumptions.csv"
    state_dumps_subdir: str = "state_dumps"
    db_subdir: str = "db"
    db_filename: str = "ICSR.db"  # Convention: filename = schema name

    @property
    def table_cards_dir(self) -> Path:
        return self.input_dir / self.table_cards_subdir

    @property
    def assumptions_catalog_file(self) -> Path:
        return (
            self.input_dir
            / self.assumptions_catalog_subdir
            / self.assumptions_catalog_filename
        )

    @property
    def query_runs_file(self) -> Path:
        return self.output_dir / self.query_runs_filename

    @property
    def query_assumptions_file(self) -> Path:
        return self.output_dir / self.query_assumptions_filename

    @property
    def state_dumps_dir(self) -> Path:
        return self.output_dir / self.state_dumps_subdir

    @property
    def database_file(self) -> Path:
        """
        Returns path to a database file (for backward compatibility).

        Note: With multi-schema support, prefer using the db_dir directly
        and letting auto-discovery find all schema databases.
        """
        return self.input_dir / self.db_subdir / self.db_filename


class EnvBaseSettings(BaseSettings):
    """Loads environment variables"""
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

class AzureSettings(EnvBaseSettings):
    """
    Settings for Azure OpenAI configuration.
    """
    openai_endpoint: AnyHttpUrl = Field(
        validation_alias="AZURE_OPENAI_ENDPOINT",
        description="Azure OpenAI base URL"
    )
    api_key: str = Field(
        validation_alias="AZURE_OPENAI_API_KEY",
        description="Azure OpenAI API Key",
        min_length=1
    )
    api_version: str = Field(
        validation_alias="AZURE_OPENAI_API_VERSION",
        description="Azure OpenAI API version",
        default="2024-02-15-preview",
    )
    default_deployment_name: str = Field(
        validation_alias="AZURE_OPENAI_DEPLOYMENT",
        description="Default Azure OpenAI deployment name",
        default="gpt-4o-mini",
    )
    max_retries: int = Field(
        validation_alias="AZURE_OPENAI_MAX_RETRIES",
        default=20,
        description="Maximum number of retries for API calls"
    )


class LangfuseSettings(EnvBaseSettings):
    """
    Settings for Langfuse integration.
    """
    public_key: str = Field(
        validation_alias="LANGFUSE_PUBLIC_KEY",
        description="Langfuse Public Key",
        min_length=1
    )
    secret_key: str = Field(
        validation_alias="LANGFUSE_SECRET_KEY",
        description="Langfuse Secret Key",
        min_length=1
    )
    host: AnyHttpUrl = Field(
        validation_alias="LANGFUSE_HOST",
        description="Langfuse Host URL"
    )


class AwsSettings(EnvBaseSettings):
    """
    Settings for AWS Bedrock configuration.

    Uses AWS Profile (AWS_PROFILE) to authenticate via ~/.aws/credentials.
    """
    region: str = Field(
        validation_alias=AliasChoices("AWS_BEDROCK_REGION", "AWS_REGION"),
        description="AWS region for Bedrock service",
        default="eu-central-1",
    )
    profile: str | None = Field(
        validation_alias=AliasChoices("AWS_PROFILE", "AWS_DEFAULT_PROFILE"),
        description="AWS profile name from ~/.aws/credentials",
        default=None,
    )
    max_retries: int = Field(
        validation_alias="AWS_BEDROCK_MAX_RETRIES",
        default=20,
        description="Maximum number of retries for API calls"
    )


class ModelConfig(BaseModel):
    """
    Configuration for a specific model instance.

    Supports both Azure OpenAI and AWS Bedrock providers.
    """
    provider: Literal["azure", "aws"] = Field(
        description="LLM provider to use"
    )
    model_name: str = Field(
        description="Model identifier (Azure deployment name or AWS model ID)"
    )
    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="Sampling temperature for model responses"
    )


class AgentSettings(BaseModel):
    """
    Per-agent model configuration.

    Each agent can use a different provider and model.
    """
    interpreter: ModelConfig = Field(
        default_factory=lambda: ModelConfig(
            provider="azure",
            model_name="gpt-4o-mini",
            temperature=0.0
        ),
        description="Model config for query interpretation agent"
    )
    drafter: ModelConfig = Field(
        default_factory=lambda: ModelConfig(
            provider="azure",
            model_name="gpt-4o-mini",
            temperature=0.0
        ),
        description="Model config for SQL drafting agent"
    )
    repairer: ModelConfig = Field(
        default_factory=lambda: ModelConfig(
            provider="azure",
            model_name="gpt-4o-mini",
            temperature=0.0
        ),
        description="Model config for SQL repair agent"
    )


class Settings(EnvBaseSettings):
    """
    Application settings combining Azure, AWS, and Langfuse configurations.

    Azure settings are required and loaded from environment variables.
    AWS and Langfuse settings are optional - if their environment variables
    are present, they will be enabled automatically.
    """
    # Provider settings
    azure: AzureSettings = Field(default_factory=AzureSettings)
    aws: AwsSettings | None = None
    langfuse: LangfuseSettings | None = None

    # Paths and workflow config
    paths: PathSettings = Field(default_factory=PathSettings)
    target_sql_dialect: str = Field(
        validation_alias="TARGET_SQL_DIALECT",
        default="sqlite",
        description="Target SQL dialect for query generation (e.g., 'sqlite', 'oracle', 'postgres')"
    )
    max_repair_attempts: int = Field(
        validation_alias="MAX_REPAIR_ATTEMPTS",
        default=3,
        description="Maximum number of SQL repair attempts when validation fails"
    )

    # Agent-specific model configuration
    agents: AgentSettings = Field(
        default_factory=AgentSettings,
        description="Per-agent model configuration"
    )

    @model_validator(mode="after")
    def load_optional_providers(self) -> "Settings":
        """Load optional provider settings if environment variables are present."""
        # Load Langfuse if available
        if self.langfuse is None:
            try:
                self.langfuse = LangfuseSettings()
            except ValidationError:
                self.langfuse = None # TODO: add logging when Langfuse is disabled due to config issues

        # Load AWS if available
        if self.aws is None:
            try:
                self.aws = AwsSettings()
            except ValidationError:
                self.aws = None

        return self

    @model_validator(mode="after")
    def parse_agent_configs_from_env(self) -> "Settings":
        """
        Parse agent configurations from environment variables.

        Supports format: {AGENT}_MODEL_PROVIDER, {AGENT}_MODEL_NAME, {AGENT}_TEMPERATURE
        Example: INTERPRETER_MODEL_PROVIDER=azure, INTERPRETER_MODEL_NAME=gpt-4o-mini
        """

        for agent_name in ["interpreter", "drafter", "repairer"]:
            provider_key = f"{agent_name.upper()}_MODEL_PROVIDER"
            model_key = f"{agent_name.upper()}_MODEL_NAME"
            temp_key = f"{agent_name.upper()}_TEMPERATURE"

            def _clean(key: str):
                val = os.getenv(key)
                if val is None:
                    return None
                stripped = val.strip()
                return stripped if stripped else None

            provider = _clean(provider_key)
            model_name = _clean(model_key)
            temperature = _clean(temp_key)

            if provider or model_name or temperature:
                # Build config from env vars
                config_dict = {}
                if provider:
                    config_dict["provider"] = provider
                if model_name:
                    config_dict["model_name"] = model_name
                if temperature:
                    config_dict["temperature"] = float(temperature)

                # Update the agent config
                current_config = getattr(self.agents, agent_name)
                updated_config = current_config.model_copy(update=config_dict)
                setattr(self.agents, agent_name, updated_config)

        return self

    @model_validator(mode="after")
    def validate_provider_availability(self) -> "Settings":
        """Ensure required providers are configured for selected agents."""
        for agent_name in ["interpreter", "drafter", "repairer"]:
            agent_config = getattr(self.agents, agent_name)

            if agent_config.provider == "aws" and self.aws is None:
                raise ValueError(
                    f"Agent '{agent_name}' is configured to use AWS provider, "
                    f"but AWS settings are not available. Please set AWS_BEDROCK_REGION "
                    f"and AWS_PROFILE."
                )

        return self
