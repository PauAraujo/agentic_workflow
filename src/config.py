from pydantic import Field, AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

class EnvBaseSettings(BaseSettings):
    """Loads environment variables"""
    model_config = SettingsConfigDict(
        env_file=".env",
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
    """
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)
    azure: AzureSettings = Field(default_factory=AzureSettings)
