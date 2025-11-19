from typing import Any, Iterable, Type, TypeVar

from pydantic import BaseModel, ValidationError
from langfuse.langchain import CallbackHandler
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import BaseMessage

T = TypeVar("T", bound=BaseModel)

def call_llm(
    llm: AzureChatOpenAI,
    langfuse_handler: CallbackHandler,
    messages: Iterable[BaseMessage],
    schema: Type[T],
) -> T:
    """
    Call the LLM with structured output validation.

    Args:
        llm: Language model instance to use
        langfuse_handler: Langfuse callback handler for tracing
        messages: Iterable of messages to send to the LLM
        schema: Pydantic model class defining the expected output schema

    Returns:
        Parsed LLM response conforming to the provided schema

    Raises:
        ValidationError: If the LLM output does not conform to the schema
    """
    structured_llm = llm.with_structured_output(schema=schema)

    try:
        llm_response = structured_llm.invoke(
            messages,
            config={"callbacks": [langfuse_handler]},
        )
    except ValidationError as exc:
        # At this point we know the model's output did not match the schema.
        # We can log and raise, or implement a fallback here in the future.
        # For now, rethrow so the caller can handle it.
        raise

    return llm_response
