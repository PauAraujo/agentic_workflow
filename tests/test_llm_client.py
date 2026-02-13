import pytest

from unittest.mock import MagicMock
from pydantic import BaseModel, Field, ValidationError
from langchain_core.exceptions import OutputParserException

from sql_query_assistant.config import ModelConfig
from sql_query_assistant.llm_client import LLMClient


class DummySchema(BaseModel):
    value: str = Field(..., description="test value")


@pytest.fixture
def client(dummy_settings):
    return LLMClient(settings=dummy_settings, langfuse_handler=None)


@pytest.fixture
def model_config():
    return ModelConfig(provider="azure", model_name="gpt-4o", temperature=0.0)


def _patch_create_llm(client, invoke_side_effect):
    """
    Patch client.create_llm so the full chain
    create_llm() -> .with_structured_output() -> .with_retry() -> .invoke()
    is controlled via *invoke_side_effect*.
    """
    mock_invoke = MagicMock(side_effect=invoke_side_effect)

    mock_retrying = MagicMock()
    mock_retrying.invoke = mock_invoke

    mock_structured = MagicMock()
    mock_structured.with_retry = MagicMock(return_value=mock_retrying)

    mock_llm = MagicMock()
    mock_llm.with_structured_output = MagicMock(return_value=mock_structured)

    client.create_llm = MagicMock(return_value=mock_llm)
    return mock_invoke, mock_structured, mock_llm


def test_call_llm_returns_result_on_success(client, model_config):
    expected = DummySchema(value="hello")
    mock_invoke, _, _ = _patch_create_llm(client, invoke_side_effect=[expected])

    result = client.call_llm(messages=[], schema=DummySchema, model_config=model_config)

    assert result == expected
    mock_invoke.assert_called_once()


def test_call_llm_passes_retry_config(client, model_config):
    """Verify that with_retry is called with the expected exception types."""
    expected = DummySchema(value="ok")
    _, mock_structured, _ = _patch_create_llm(client, invoke_side_effect=[expected])

    client.call_llm(
        messages=[], schema=DummySchema, model_config=model_config, max_retries=5
    )

    mock_structured.with_retry.assert_called_once()
    call_kwargs = mock_structured.with_retry.call_args.kwargs
    assert ValidationError in call_kwargs["retry_if_exception_type"]
    assert OutputParserException in call_kwargs["retry_if_exception_type"]
    assert call_kwargs["stop_after_attempt"] == 5
    assert call_kwargs["wait_exponential_jitter"] is True


def test_call_llm_uses_function_calling_method(client, model_config):
    """Verify that with_structured_output is called with method='function_calling'."""
    expected = DummySchema(value="ok")
    _, _, mock_llm = _patch_create_llm(client, invoke_side_effect=[expected])

    client.call_llm(messages=[], schema=DummySchema, model_config=model_config)

    mock_llm.with_structured_output.assert_called_once_with(
        schema=DummySchema, method="function_calling"
    )


def test_call_llm_propagates_non_schema_errors(client, model_config):
    """Non-schema errors (e.g. RuntimeError) should propagate immediately."""
    _patch_create_llm(client, invoke_side_effect=RuntimeError("connection lost"))

    with pytest.raises(RuntimeError, match="connection lost"):
        client.call_llm(messages=[], schema=DummySchema, model_config=model_config)
