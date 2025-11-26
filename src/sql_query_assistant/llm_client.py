from typing import Sequence, Type, TypeVar
from pydantic import BaseModel
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from langchain_core.messages import BaseMessage
from langchain_openai import AzureChatOpenAI

from .config import Settings

T = TypeVar("T", bound=BaseModel)

class OpenAILLMClient:
    """Client for interacting with Azure OpenAI LLMs with structured output support."""
    def __init__(self, settings: Settings, langfuse_handler: CallbackHandler | None = None):
        self.settings = settings
        self.langfuse_handler = langfuse_handler

    @classmethod
    def from_settings(cls, settings: Settings, langfuse_handler: CallbackHandler | None = None) -> "OpenAILLMClient":
        """
        Create an OpenAILLMClient instance from Settings.

        Args:
            settings: Settings instance with configuration
            langfuse_handler: Optional Langfuse callback handler for tracing

        Returns:
            OpenAILLMClient instance
        """
        return cls(settings=settings, langfuse_handler=langfuse_handler)

    def get_llm(
        self,
        deployment_name: str | None,
        temperature: float,
    ) -> AzureChatOpenAI:
        """
        Get an AzureChatOpenAI instance with specified model and temperature.

        Args:
            deployment_name: Optional deployment name. If None, uses the default from settings.
            temperature: Sampling temperature to use for this instance.

        Returns:
            Configured AzureChatOpenAI instance
        """
        callbacks = [self.langfuse_handler] if self.langfuse_handler else None
        return AzureChatOpenAI(
            azure_endpoint=str(self.settings.azure.openai_endpoint),
            api_version=self.settings.azure.api_version,
            api_key=self.settings.azure.api_key,
            azure_deployment=deployment_name or self.settings.azure.default_deployment_name,
            temperature=temperature,
            max_retries=self.settings.azure.max_retries,
            callbacks=callbacks,
        )

    def call_llm(
        self,
        messages: Sequence[BaseMessage],
        schema: Type[T],
        deployment_name: str | None = None,
        temperature: float = 0.0,
    ) -> T:
        """
        Call the LLM with structured output validation.

        Args:
            messages: Sequence of messages to send to the LLM
            schema: Pydantic model class defining the expected output schema
            deployment_name: Optional model deployment name to override default
            temperature: Temperature parameter for the LLM (default: 0.0)

        Returns:
            Parsed LLM response conforming to the provided schema
        """
        llm = self.get_llm(deployment_name, temperature)
        structured_llm = llm.with_structured_output(schema=schema)

        return structured_llm.invoke(messages)


def create_llm_client() -> OpenAILLMClient:
    """
    Create an OpenAILLMClient with optional Langfuse integration.

    This is a convenience factory that handles the common initialization pattern:
    1. Loads settings from environment variables
    2. Initializes Langfuse if credentials are available
    3. Returns a configured client ready for use

    Returns:
        Configured OpenAILLMClient instance
    """
    settings = Settings()
    handler = None
    if settings.langfuse is not None:
        Langfuse(
            public_key=settings.langfuse.public_key,
            secret_key=settings.langfuse.secret_key,
            host=str(settings.langfuse.host),
        )
        handler = CallbackHandler()
    return OpenAILLMClient.from_settings(settings, langfuse_handler=handler)