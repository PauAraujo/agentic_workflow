import os

from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from langfuse.langchain import CallbackHandler

load_dotenv()


def get_langfuse_handler():
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    if not public_key:
        raise RuntimeError("LANGFUSE_PUBLIC_KEY is not set")

    return CallbackHandler(public_key=public_key)


def get_llm(temperature: float = 0.7) -> AzureChatOpenAI:
    """
    Initialize and return the Azure OpenAI LLM.

    Args:
        temperature: Temperature parameter for the LLM (default: 0.7)

    Returns:
        Configured AzureChatOpenAI instance
    """
    return AzureChatOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
        temperature=temperature,
    )