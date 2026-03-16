import logging

from typing import Sequence, Type, TypeVar
from pydantic import BaseModel, ValidationError
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from langchain_aws import ChatBedrock
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import BaseMessage
from langchain_core.exceptions import OutputParserException

from sql_query_assistant.config import Settings, ModelConfig

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    """Builds LangChain chat models for any configured provider (Azure or AWS)."""

    def __init__(self, settings: Settings, langfuse_handler: CallbackHandler | None = None):
        self.settings = settings
        self._callbacks = [langfuse_handler] if langfuse_handler else None

    def create_llm(self, model_config: ModelConfig) -> AzureChatOpenAI | ChatBedrock:
        """Return an Azure or AWS chat model based on *model_config.model_provider*."""
        if model_config.model_provider == "azure":
            return self._create_azure_llm(model_config)
        elif model_config.model_provider == "aws":
            return self._create_aws_llm(model_config)
        else:
            raise ValueError(f"Unsupported provider: {model_config.model_provider}")

    def call_llm(
        self,
        messages: Sequence[BaseMessage],
        schema: Type[T],
        model_config: ModelConfig,
        max_retries: int = 3,
    ) -> T:
        """Call the LLM with structured output and automatic retries on schema errors."""
        llm = self.create_llm(model_config)
        structured_llm = llm.with_structured_output(
            schema=schema, method="function_calling"
        )
        retrying_llm = structured_llm.with_retry(
            retry_if_exception_type=(ValidationError, OutputParserException),
            stop_after_attempt=max_retries,
            wait_exponential_jitter=True,
        )
        return retrying_llm.invoke(messages)

    def _create_azure_llm(self, model_config: ModelConfig) -> AzureChatOpenAI:
        logger.debug(
            "Creating AzureChatOpenAI (deployment=%s, temp=%.2f)",
            model_config.model_name,
            model_config.temperature,
        )
        return AzureChatOpenAI(
            azure_endpoint=str(self.settings.azure.endpoint),
            api_version=self.settings.azure.api_version,
            api_key=self.settings.azure.api_key,
            azure_deployment=model_config.model_name,
            temperature=model_config.temperature,
            max_retries=self.settings.azure.max_retries,
            callbacks=self._callbacks,
        )

    def _create_aws_llm(self, model_config: ModelConfig) -> ChatBedrock:
        if not self.settings.aws:
            raise ValueError(
                "AWS Bedrock settings not configured. Set AWS_REGION and AWS_PROFILE."
            )
        logger.debug(
            "Creating ChatBedrock (model=%s, temp=%.2f, region=%s)",
            model_config.model_name,
            model_config.temperature,
            self.settings.aws.region,
        )
        return ChatBedrock(
            model_id=model_config.model_name,
            region_name=self.settings.aws.region,
            credentials_profile_name=self.settings.aws.profile,
            temperature=model_config.temperature,
            callbacks=self._callbacks,
        )


def create_llm_client(settings: Settings) -> LLMClient:
    """Create an LLMClient with optional Langfuse tracing."""
    handler = None
    if settings.langfuse:
        try:
            # Langfuse() registers credentials with the SDK globally.
            # CallbackHandler() then uses those credentials to send LLM traces.
            Langfuse(
                public_key=settings.langfuse.public_key,
                secret_key=settings.langfuse.secret_key,
                host=str(settings.langfuse.host),
            )
            handler = CallbackHandler()
        except Exception as exc:
            logger.warning("Langfuse init failed, continuing without tracing: %s", exc)
    return LLMClient(settings=settings, langfuse_handler=handler)
