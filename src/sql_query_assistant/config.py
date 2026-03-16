import logging

from pathlib import Path
from typing import Literal, Self
from pydantic import (
    Field,
    BaseModel,
    AnyHttpUrl,
    SecretStr,
    ValidationError,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class PathSettings(BaseModel):
    """Paths to input/output directories used by the workflow."""

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
        return self.input_dir / self.schemas_dir


class DatabaseSettings(BaseSettings):
    """Database backend selection and Oracle connection settings."""

    model_config = SettingsConfigDict(env_prefix="DB_")

    type: Literal["sqlite", "oracle"] = Field(
        default="sqlite", description="Database backend: 'sqlite' or 'oracle'"
    )
    host: str | None = Field(default=None, description="Oracle database hostname")
    port: int = Field(default=1521, description="Oracle database port")
    service: str | None = Field(default=None, description="Oracle service name")
    user: str | None = Field(default=None, description="Oracle database username")
    password: str | None = Field(default=None, description="Oracle database password")

    @model_validator(mode="after")
    def validate_oracle_credentials(self) -> Self:
        if self.type == "oracle":
            missing = []
            if not self.host:
                missing.append("DB_HOST")
            if not self.service:
                missing.append("DB_SERVICE")
            if not self.user:
                missing.append("DB_USER")
            if not self.password:
                missing.append("DB_PASSWORD")
            if missing:
                raise ValueError(
                    f"Oracle credentials required when DB_TYPE=oracle. "
                    f"Missing: {', '.join(missing)}"
                )
        return self


class AzureOpenAISettings(BaseSettings):
    """Azure OpenAI provider settings."""

    model_config = SettingsConfigDict(env_prefix="AZURE_OPENAI_")

    endpoint: AnyHttpUrl = Field(description="Azure OpenAI base URL")
    api_key: SecretStr = Field(description="Azure OpenAI API key")
    api_version: str = Field(default="2024-02-15-preview", description="Azure OpenAI API version")
    max_retries: int = Field(default=20, description="Maximum retries for API calls")


class LangfuseSettings(BaseSettings):
    """Langfuse observability settings."""

    model_config = SettingsConfigDict(env_prefix="LANGFUSE_")

    public_key: str = Field(description="Langfuse public key")
    secret_key: str = Field(description="Langfuse secret key")
    host: AnyHttpUrl = Field(description="Langfuse host URL")


class AzureSearchSettings(BaseSettings):
    """Azure AI Search integration settings."""

    model_config = SettingsConfigDict(env_prefix="AZURE_SEARCH_")

    endpoint: AnyHttpUrl = Field(description="Azure AI Search endpoint URL")
    query_key: str = Field(description="Azure AI Search query key")
    table_cards_index: str = Field(
        default="sql_assistant_table_cards_index", description="Name of the table cards search index"
    )
    top_k: int = Field(default=50, ge=1, le=100, description="Initial search candidate pool size")
    reranker_top_k: int = Field(
        default=10, ge=1, le=250, description="Results to keep after semantic reranking"
    )
    fk_expansion_enabled: bool = Field(default=True, description="Enable FK relationship expansion")
    fk_expansion_source_count: int = Field(
        default=3, ge=0, le=10, description="Top tables to use as FK expansion sources"
    )
    fk_expansion_max_total: int = Field(
        default=25, ge=1, le=50, description="Maximum total tables after FK expansion"
    )
    fk_expansion_include_reverse: bool = Field(
        default=False, description="Include reverse FK relationships"
    )
    embedding_deployment: str = Field(
        default="text-embedding-3-small", description="Azure OpenAI deployment for embeddings"
    )
    embedding_dimensions: int = Field(
        default=1536, description="Embedding vector dimensions"
    )
    hybrid_search_enabled: bool = Field(
        default=True, description="Enable hybrid search (BM25 + vector); falls back to lexical if False"
    )


class TableSelectionSettings(BaseSettings):
    """Settings for the Table Selector module."""

    model_config = SettingsConfigDict(env_prefix="TABLE_SELECTOR_")

    core_tables: list[str] = Field(
        default=[
            "ICSR.SAFETY_REPORT",
            "ICSR.PATIENT",
            "ICSR.DRUG",
            "ICSR.REACTION",
        ],
        description="Core tables always shown as 'other available' options (safety net for retriever misses)",
    )
    noise_value_maps: list[str] = Field(
        default=["NULL_FLAVOUR", "DATE_PRECISION", "NULLFLAVOR"],
        description="Value map names to filter out (technical metadata, not business-meaningful)",
    )


class AwsSettings(BaseSettings):
    """AWS Bedrock provider settings."""

    model_config = SettingsConfigDict(env_prefix="AWS_")

    region: str = Field(default="eu-central-1", description="AWS region for Bedrock")
    profile: str = Field(description="AWS profile name from ~/.aws/credentials")


class ModelConfig(BaseSettings):
    """Base model configuration for an LLM agent."""

    model_provider: Literal["azure", "aws"] = Field(default="azure", description="LLM provider")
    model_name: str = Field(
        default="gpt-4o-mini", description="Model identifier (Azure deployment name or AWS model ID)"
    )
    temperature: float = Field(default=0.0, ge=0.0, le=2.0, description="Sampling temperature")


class DrafterModelConfig(ModelConfig):
    """Drafter model config, reads from DRAFTER_* env vars."""

    model_config = SettingsConfigDict(env_prefix="DRAFTER_")


class RepairerModelConfig(ModelConfig):
    """Repairer model config, reads from REPAIRER_* env vars."""

    model_config = SettingsConfigDict(env_prefix="REPAIRER_")


class TableSelectorModelConfig(ModelConfig):
    """Table selector model config, reads from TABLE_SELECTOR_* env vars."""

    model_config = SettingsConfigDict(env_prefix="TABLE_SELECTOR_")


class AgentSettings(BaseModel):
    """Per-agent model configuration, grouping all agent configs together."""

    drafter: DrafterModelConfig = Field(
        default_factory=DrafterModelConfig, description="Model config for SQL drafting agent"
    )
    repairer: RepairerModelConfig = Field(
        default_factory=RepairerModelConfig, description="Model config for SQL repair agent"
    )
    table_selector: TableSelectorModelConfig = Field(
        default_factory=TableSelectorModelConfig, description="Model config for table selection agent"
    )


class Settings(BaseSettings):
    """Master settings, assembles providers, agent configs, and workflow knobs."""

    # Providers
    azure: AzureOpenAISettings = Field(default_factory=AzureOpenAISettings)
    aws: AwsSettings | None = None
    langfuse: LangfuseSettings | None = None
    azure_search: AzureSearchSettings | None = None

    # Module settings
    table_selection: TableSelectionSettings = Field(
        default_factory=TableSelectionSettings
    )

    # Database backend
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)

    # Paths and workflow config
    paths: PathSettings = Field(default_factory=PathSettings)
    target_sql_dialect: Literal["sqlite", "oracle"] = Field(
        default="sqlite", description="Target SQL dialect for query generation"
    )
    max_repair_attempts: int = Field(
        default=3, description="Maximum SQL repair attempts when validation fails"
    )
    persist_enabled: bool = Field(
        default=True, description="Whether to persist workflow results to disk"
    )

    # Per-agent model configuration
    agents: AgentSettings = Field(
        default_factory=AgentSettings, description="Per-agent model configuration"
    )

    @model_validator(mode="after")
    def load_optional_providers(self) -> Self:
        """Try to load each optional provider from env vars; leave as None if missing."""
        for attr, settings_class in [
            ("aws", AwsSettings),
            ("langfuse", LangfuseSettings),
            ("azure_search", AzureSearchSettings),
        ]:
            if getattr(self, attr) is None:
                try:
                    setattr(self, attr, settings_class())
                except ValidationError:
                    pass
        return self

    @model_validator(mode="after")
    def validate_provider_availability(self) -> Self:
        """Ensure required provider settings exist for each agent's chosen provider."""
        for agent_name in ("drafter", "repairer", "table_selector"):
            config = getattr(self.agents, agent_name)
            if config.model_provider == "aws" and self.aws is None:
                raise ValueError(
                    f"Agent '{agent_name}' uses 'aws' provider but AWS settings "
                    f"are missing. Set AWS_REGION and AWS_PROFILE."
                )
        return self
