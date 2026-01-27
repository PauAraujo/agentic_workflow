import os

from pathlib import Path
from typing import Literal
from pydantic import (
    Field,
    BaseModel,
    ConfigDict,
    AnyHttpUrl,
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
    Paths to input/output directories used by the workflow.

    The base fields can be overridden via environment settings, while
    the derived properties keep call sites simple and consistent.
    """
    input_dir: Path = PROJECT_ROOT / "input"
    output_dir: Path = PROJECT_ROOT / "output"
    table_cards_subdir: str = "table_cards"
    query_runs_filename: str = "query_runs.csv"
    state_dumps_subdir: str = "state_dumps"
    schemas_dir: str = "schemas_dir"

    @property
    def table_cards_dir(self) -> Path:
        return self.input_dir / self.table_cards_subdir

    @property
    def query_runs_file(self) -> Path:
        return self.output_dir / self.query_runs_filename

    @property
    def state_dumps_dir(self) -> Path:
        return self.output_dir / self.state_dumps_subdir

    @property
    def db_dir(self) -> Path:
        """The directory containing all schema database files (.db)."""
        return self.input_dir / self.schemas_dir

    def get_database_path(self, schema_name: str = "ICSR") -> Path:
        """
        Get the path to a specific schema database file.

        Args:
            schema_name: Name of the schema (default: ICSR)

        Returns:
            Path to the schema database file
        """
        return self.db_dir / f"{schema_name}.db"


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


class AzureSearchSettings(EnvBaseSettings):
    """
    Settings for Azure AI Search integration.
    """
    endpoint: AnyHttpUrl = Field(
        validation_alias="AZURE_SEARCH_ENDPOINT",
        description="Azure AI Search endpoint URL"
    )
    query_key: str = Field(
        validation_alias="AZURE_SEARCH_QUERY_KEY",
        description="Azure AI Search query key for searching",
        min_length=1
    )
    table_cards_index_name: str = Field(
        validation_alias="AZURE_SEARCH_TABLE_CARDS_INDEX",
        default="sql_assistant_table_cards_index",
        description="Name of the table cards index in Azure AI Search"
    )
    top_k: int = Field(
        validation_alias="AZURE_SEARCH_TOP_K",
        default=50,
        description="Number of top relevant table cards to retrieve from initial search",
        ge=1,
        le=100
    )
    reranker_top_k: int = Field(
        validation_alias="AZURE_SEARCH_RERANKER_TOP_K",
        default=10,
        description="Number of table cards to select after semantic reranking (from the top_k candidate pool)",
        ge=1,
        le=250
    )
    fk_expansion_enabled: bool = Field(
        validation_alias="FK_EXPANSION_ENABLED",
        default=True,
        description="Enable FK relationship expansion for top tables"
    )
    fk_expansion_source_count: int = Field(
        validation_alias="FK_EXPANSION_SOURCE_COUNT",
        default=3,
        description="Number of top core tables to use as source for FK expansion",
        ge=0,
        le=10
    )
    fk_expansion_max_total: int = Field(
        validation_alias="FK_EXPANSION_MAX_TOTAL",
        default=25,
        description="Maximum total table cards after FK expansion",
        ge=1,
        le=50
    )
    fk_expansion_include_reverse: bool = Field(
        validation_alias="FK_EXPANSION_INCLUDE_REVERSE",
        default=False,
        description="Include reverse FK relationships (tables that reference the core tables)"
    )
    # Embedding configuration for hybrid search
    embedding_deployment: str = Field(
        validation_alias="AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
        default="text-embedding-3-small",
        description="Azure OpenAI deployment name for embeddings"
    )
    embedding_dimensions: int = Field(
        validation_alias="AZURE_OPENAI_EMBEDDING_DIMENSIONS",
        default=1536,
        description="Embedding vector dimensions (1536 for text-embedding-3-small/ada-002)"
    )
    hybrid_search_enabled: bool = Field(
        validation_alias="HYBRID_SEARCH_ENABLED",
        default=True,
        description="Enable hybrid search (BM25 + vector). Falls back to lexical if False"
    )


class TableSelectorSettings(EnvBaseSettings):
    """
    Settings for the Table Selector module.
    """
    core_tables: list[str] = Field(
        validation_alias="TABLE_SELECTOR_CORE_TABLES",
        default=[
            "ICSR.SAFETY_REPORT",
            "ICSR.PATIENT",
            "ICSR.DRUG",
            "ICSR.REACTION",
        ],
        description="Core tables always shown as 'other available' options (safety net)"
    )
    noise_value_maps: list[str] = Field(
        validation_alias="TABLE_SELECTOR_NOISE_VALUE_MAPS",
        default=[
            "NULL_FLAVOUR",
            "DATE_PRECISION",
            "NULLFLAVOR",
        ],
        description="Value map names to filter out (technical metadata, not business-meaningful)"
    )


class AwsSettings(EnvBaseSettings):
    """
    Settings for AWS Bedrock configuration.

    Uses AWS Profile (AWS_PROFILE) to authenticate via ~/.aws/credentials.
    """
    region: str = Field(
        validation_alias="AWS_REGION",
        description="AWS region for Bedrock service",
        default="eu-central-1",
    )
    profile: str | None = Field(
        validation_alias="AWS_PROFILE",
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
    Used both at runtime (for LLM calls) and for persistence (in RunRecord).
    """

    model_config = ConfigDict(frozen=True)

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
    Also used as the persistence snapshot in RunRecord.
    """

    model_config = ConfigDict(frozen=True)

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
    table_selector: ModelConfig = Field(
        default_factory=lambda: ModelConfig(
            provider="azure",
            model_name="gpt-4o-mini",
            temperature=0.0
        ),
        description="Model config for table selection agent"
    )


class Settings(EnvBaseSettings):
    """
    Application settings combining Azure OpenAI, AWS Bedrock, Langfuse,
    Azure Search, table selector, paths, and per-agent model configurations.

    Azure settings are required and loaded from environment variables.
    AWS and Langfuse settings are optional - if their environment variables
    are present, they will be enabled automatically.
    """
    # Provider settings
    azure: AzureSettings = Field(default_factory=AzureSettings)
    aws: AwsSettings | None = None
    langfuse: LangfuseSettings | None = None
    azure_search: AzureSearchSettings | None = None
    table_selector: TableSelectorSettings = Field(default_factory=TableSelectorSettings)

    # Paths and workflow config
    paths: PathSettings = Field(default_factory=PathSettings)
    target_sql_dialect: str = Field(
        validation_alias="TARGET_SQL_DIALECT",
        default="sqlite",
        description="Target SQL dialect for query generation (e.g., 'sqlite', 'oracle', 'postgres')"
    )
    max_repair_attempts: int = Field(
        validation_alias="MAX_REPAIR_ATTEMPTS",
        default=1,
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
                self.langfuse = None

        # Load AWS if available
        if self.aws is None:
            try:
                self.aws = AwsSettings()
            except ValidationError:
                self.aws = None

        # Load Azure Search if available
        if self.azure_search is None:
            try:
                self.azure_search = AzureSearchSettings()
            except ValidationError:
                self.azure_search = None

        return self

    @model_validator(mode="after")
    def parse_agent_configs_from_env(self) -> "Settings":
        """
        Parse agent configurations from environment variables.

        Supports format: {AGENT}_MODEL_PROVIDER, {AGENT}_MODEL_NAME, {AGENT}_TEMPERATURE
        Example: DRAFTER_MODEL_PROVIDER=azure, DRAFTER_MODEL_NAME=gpt-4o
        """

        for agent_name in ["drafter", "repairer", "table_selector"]:
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

                # Update the agent config (immutable pattern for frozen model)
                current_config = getattr(self.agents, agent_name)
                updated_config = current_config.model_copy(update=config_dict)
                self.agents = self.agents.model_copy(update={agent_name: updated_config})

        return self

    @model_validator(mode="after")
    def validate_provider_availability(self) -> "Settings":
        """Ensure required providers are configured for selected agents."""
        for agent_name in ["drafter", "repairer", "table_selector"]:
            agent_config = getattr(self.agents, agent_name)

            if agent_config.provider == "aws" and self.aws is None:
                raise ValueError(
                    f"Agent '{agent_name}' is configured to use AWS provider, "
                    f"but AWS settings are not available. Please set AWS_REGION "
                    f"and AWS_PROFILE."
                )

        return self
