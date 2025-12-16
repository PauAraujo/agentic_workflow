import pytest

from typing import cast
from tests.conftest import DummyLLMClient
from sql_query_assistant.domain import (
    IntentCard,
    InterpreterResponse,
    SelectedAssumption,
)
from sql_query_assistant.llm_client import OpenAILLMClient
from sql_query_assistant.modules.sql_drafter.models import RawSQLDraftResponse
from sql_query_assistant.modules.sql_drafter.nodes import draft_sql


def _make_sql_drafter_client(sql, rationale, tables_used):
    """Create a DummyLLMClient with a SQL draft response."""
    llm_response = RawSQLDraftResponse(
        sql=sql,
        rationale=rationale,
        tables_used=tables_used,
    )
    return cast(OpenAILLMClient, DummyLLMClient(llm_response))


def _make_drafter_state(intent_card, table_cards):
    """Build a standard workflow state dict for SQL drafter tests."""
    return {
        "intent_card": intent_card,
        "table_cards": table_cards if isinstance(table_cards, list) else [table_cards],
    }


@pytest.fixture
def intent_card(sample_assumption_catalog):
    """Construct a minimal intent card for drafting tests."""
    base_assumption = sample_assumption_catalog[0]
    selected = SelectedAssumption(
        assumption_id=base_assumption.id,
        assumption_label=base_assumption.label,
        selected_value=base_assumption.options[0].value,
        selected_label=base_assumption.options[0].label,
        option_description=base_assumption.options[0].description,
        rationale="User asked for male only cases",
        available_options=None,
    )
    return IntentCard(
        task="Count male cases by year",
        assumption_response=InterpreterResponse(assumption_choices=[selected]),
    )


def test_draft_sql_returns_sql_draft(intent_card, sample_table_card, dummy_settings):
    """Wrap the structured LLM response into an SQLDraft and persist it in workflow state."""
    client = _make_sql_drafter_client(
        sql="SELECT COUNT(DISTINCT SAFETY_REPORT_ID) FROM ICSR.PATIENT WHERE PATIENT_SEX_ID = 1;",
        rationale="Counts unique cases limited to male sex code.",
        tables_used=["ICSR.PATIENT"],
    )
    state = _make_drafter_state(intent_card, sample_table_card)

    result = draft_sql(state, client, dummy_settings)

    assert "sql_draft" in result
    sql_draft = result["sql_draft"]

    # Verify the SQLDraft contains the LLM response data
    assert sql_draft.sql.startswith("SELECT COUNT")
    assert "ICSR.PATIENT" in sql_draft.tables_used
    assert sql_draft.rationale == "Counts unique cases limited to male sex code."


def test_draft_sql_formats_prompt(intent_card, sample_table_card, dummy_settings):
    """Verify prompt structure includes intent card and table metadata with correct LLM parameters."""
    client = _make_sql_drafter_client(
        sql="SELECT 1;",
        rationale="noop",
        tables_used=["ICSR.PATIENT"],
    )
    state = _make_drafter_state(intent_card, sample_table_card)

    draft_sql(state, client, dummy_settings)

    # Verify two-message prompt structure
    assert client.last_messages is not None
    assert len(client.last_messages) == 2

    system_message = client.last_messages[0]
    human_message = client.last_messages[1]

    # Verify prompt content
    assert "SQL Drafting Agent" in system_message.content
    assert "Target SQL Dialect" in human_message.content
    assert intent_card.task in human_message.content
    assert "ICSR.PATIENT" in human_message.content
    assert intent_card.assumption_response.assumption_choices[0].assumption_id in human_message.content

    # Verify LLM call parameters
    assert client.last_schema == RawSQLDraftResponse
    assert client.last_deployment_name == "gpt-4o-mini"
    assert client.last_temperature == 0.0
