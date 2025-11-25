from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from .config import Settings
from .llm_client import OpenAILLMClient


def create_llm_client() -> OpenAILLMClient:
    """Create an OpenAILLMClient with optional Langfuse integration."""
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
