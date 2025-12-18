import boto3
import logging

from botocore.config import Config
from pydantic import BaseModel
from typing import Sequence, Type, TypeVar
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from langchain_core.messages import BaseMessage
from langchain_openai import AzureChatOpenAI
from langchain_aws import ChatBedrock

from .config import Settings, ModelConfig

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

class LLMClient:
    """
    LLM client supporting multiple providers (Azure OpenAI, AWS Bedrock).

    Routes LLM calls to the appropriate provider based on ModelConfig.
    """

    def __init__(self, settings: Settings, langfuse_handler: CallbackHandler | None = None):
        self.settings = settings
        self.langfuse_handler = langfuse_handler

    @classmethod
    def from_settings(cls, settings: Settings, langfuse_handler: CallbackHandler | None = None) -> "LLMClient":
        """
        Create a LLMClient instance from Settings.

        Args:
            settings: Settings instance with configuration
            langfuse_handler: Optional Langfuse callback handler for tracing

        Returns:
            LLMClient instance
        """
        return cls(settings=settings, langfuse_handler=langfuse_handler)

    def _get_azure_llm(self, model_config: ModelConfig) -> AzureChatOpenAI:
        """Create an AzureChatOpenAI instance with specified configuration."""
        callbacks = [self.langfuse_handler] if self.langfuse_handler else None

        logger.debug(
            "Creating AzureChatOpenAI client (deployment=%s, temp=%.2f, retries=%d)",
            model_config.model_name,
            model_config.temperature,
            self.settings.azure.max_retries,
        )

        return AzureChatOpenAI(
            azure_endpoint=str(self.settings.azure.openai_endpoint),
            api_version=self.settings.azure.api_version,
            api_key=self.settings.azure.api_key,
            azure_deployment=model_config.model_name,
            temperature=model_config.temperature,
            max_retries=self.settings.azure.max_retries,
            callbacks=callbacks,
        )

    def _get_aws_llm(self, model_config: ModelConfig) -> ChatBedrock:
        """Create a ChatBedrock instance with specified configuration."""
        if not self.settings.aws:
            raise ValueError(
                "AWS Bedrock settings not configured. "
                "Set AWS_BEDROCK_REGION and AWS_PROFILE."
            )

        callbacks = [self.langfuse_handler] if self.langfuse_handler else None

        logger.debug(
            "Creating ChatBedrock client (model=%s, temp=%.2f, region=%s, profile=%s)",
            model_config.model_name,
            model_config.temperature,
            self.settings.aws.region,
            self.settings.aws.profile or "default",
        )

        # Build model kwargs with temperature
        model_kwargs = {"temperature": model_config.temperature}

        # Create boto3 session using AWS Profile
        session = boto3.Session(profile_name=self.settings.aws.profile)

        # Create retry configuration
        retry_config = Config(
            retries={
                "max_attempts": self.settings.aws.max_retries,
                "mode": "adaptive"
            }
        )
        bedrock_client = session.client(
            "bedrock-runtime",
            region_name=self.settings.aws.region,
            config=retry_config
        )

        return ChatBedrock(
            model_id=model_config.model_name,
            client=bedrock_client,
            model_kwargs=model_kwargs,
            callbacks=callbacks,
        )

    def get_llm(self, model_config: ModelConfig):
        """
        Get an LLM instance based on provider specified in ModelConfig.

        Args:
            model_config: Configuration specifying provider, model, and temperature

        Returns:
            AzureChatOpenAI or ChatBedrock instance
        """
        if model_config.provider == "azure":
            return self._get_azure_llm(model_config)
        elif model_config.provider == "aws":
            return self._get_aws_llm(model_config)
        else:
            raise ValueError(f"Unsupported provider: {model_config.provider}")

    def call_llm(
        self,
        messages: Sequence[BaseMessage],
        schema: Type[T],
        model_config: ModelConfig,
    ) -> T:
        """
        Call the LLM with structured output validation.

        Args:
            messages: Sequence of messages to send to the LLM
            schema: Pydantic model class defining the expected output schema
            model_config: Configuration for provider, model, and temperature

        Returns:
            Parsed LLM response conforming to the provided schema
        """
        llm = self.get_llm(model_config)
        structured_llm = llm.with_structured_output(schema=schema)

        return structured_llm.invoke(messages)


def create_llm_client(settings: Settings) -> LLMClient:
    """
    Create a LLMClient with optional Langfuse integration.

    This is a convenience factory that handles the common initialization pattern:
    1. Initializes Langfuse if credentials are available in settings
    2. Returns a configured client ready for use

    Args:
        settings: Settings instance (already loaded from environment variables)

    Returns:
        Configured LLMClient instance
    """
    handler = None
    if settings.langfuse is not None:
        try:
            logger.info("Initializing Langfuse tracing")
            Langfuse(
                public_key=settings.langfuse.public_key,
                secret_key=settings.langfuse.secret_key,
                host=str(settings.langfuse.host),
            )
            handler = CallbackHandler()
        except Exception as exc:
            logger.warning("Langfuse initialization failed, continuing without tracing: %s", exc)
    else:
        logger.info("Langfuse tracing disabled (no LANGFUSE_* env vars)")
    return LLMClient.from_settings(settings, langfuse_handler=handler)
