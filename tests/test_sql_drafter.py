import pytest

from conftest import DummyLLMClient
from sql_query_assistant.domain import (
    IntentCard,
    InterpreterResponse,
    SelectedAssumption,
)
from sql_query_assistant.modules.sql_drafter.models import RawSQLDraftResponse
from sql_query_assistant.modules.sql_drafter.nodes import draft_sql

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


def test_draft_sql_returns_sql_draft(intent_card, sample_table_card):
    """
    Wrap the structured LLM response into an SQLDraft and persist it in workflow state.
    """
    llm_response = RawSQLDraftResponse(
        sql="SELECT COUNT(DISTINCT SAFETY_REPORT_ID) FROM ICSR.PATIENT WHERE PATIENT_SEX_ID = 1;",
        rationale="Counts unique cases limited to male sex code.",
        tables_used=["ICSR.PATIENT"],
    )
    client = DummyLLMClient(llm_response)

    state = {"intent_card": intent_card, "table_cards": [sample_table_card]}

    result = draft_sql(state, client)

    assert "sql_draft" in result
    sql_draft = result["sql_draft"]

    assert sql_draft.sql.startswith("SELECT COUNT")
    assert "ICSR.PATIENT" in sql_draft.tables_used
    assert sql_draft.rationale == "Counts unique cases limited to male sex code."


def test_draft_sql_formats_prompt(intent_card, sample_table_card):
    """
    Build a two-message prompt containing the intent card and table metadata.
    """
    llm_response = RawSQLDraftResponse(sql="SELECT 1;", rationale="noop", tables_used=["ICSR.PATIENT"])
    client = DummyLLMClient(llm_response)

    state = {"intent_card": intent_card, "table_cards": [sample_table_card]}

    draft_sql(state, client)

    assert client.last_messages is not None
    assert len(client.last_messages) == 2

    system_message = client.last_messages[0]
    human_message = client.last_messages[1]

    assert "SQL Drafting Agent" in system_message.content
    assert intent_card.task in human_message.content
    assert "ICSR.PATIENT" in human_message.content
    assert intent_card.assumption_response.assumption_choices[0].assumption_id in human_message.content

    assert client.last_schema == RawSQLDraftResponse
    assert client.last_deployment_name == "gpt-4o-mini"
    assert client.last_temperature == 0.0


def test_draft_sql_raises_on_wrong_schema(intent_card, sample_table_card):
    """
    Raise TypeError if LLM response does not match expected RawSQLDraftResponse schema.
    """
    client = DummyLLMClient(response="not a RawSQLDraftResponse")
    state = {"intent_card": intent_card, "table_cards": [sample_table_card]}

    with pytest.raises(TypeError):
        draft_sql(state, client)
