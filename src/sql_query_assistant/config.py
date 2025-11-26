from pathlib import Path
from pydantic import AnyHttpUrl, Field, ValidationError, model_validator, BaseModel
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
    table_cards_subdir: str = "table_cards"
    assumptions_catalog_subdir: str = "assumptions_catalog"
    assumptions_catalog_filename: str = "assumptions_catalog.yaml"

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

class Settings(EnvBaseSettings):
    """
    Application settings combining Azure and Langfuse configurations.

    Azure settings are required and loaded from environment variables.
    Langfuse settings are optional - if LANGFUSE_* environment variables
    are present, observability tracing will be enabled automatically.
    Otherwise, the application runs without tracing.
    """
    azure: AzureSettings = Field(default_factory=AzureSettings)
    langfuse: LangfuseSettings | None = None
    paths: PathSettings = Field(default_factory=PathSettings)

    @model_validator(mode="after")
    def load_langfuse_if_available(self) -> "Settings":
        if self.langfuse is None:
            try:
                self.langfuse = LangfuseSettings()
            except ValidationError:
                self.langfuse = None
        return self
