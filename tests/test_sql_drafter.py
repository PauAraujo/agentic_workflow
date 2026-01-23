from typing import cast

from tests.conftest import DummyLLMClient
from sql_query_assistant.llm_client import LLMClient
from sql_query_assistant.domain import TableCardWithSelection
from sql_query_assistant.modules.sql_drafter.models import RawSQLDraftResponse
from sql_query_assistant.modules.sql_drafter.nodes import draft_sql


def _make_sql_drafter_client(sql, rationale, tables_used):
    """Create a DummyLLMClient with a SQL draft response."""
    llm_response = RawSQLDraftResponse(
        sql=sql,
        rationale=rationale,
        tables_used=tables_used,
    )
    return cast(LLMClient, DummyLLMClient(llm_response))


def _make_drafter_state(user_query, table_cards):
    """Build a standard workflow state dict for SQL drafter tests."""
    cards = table_cards if isinstance(table_cards, list) else [table_cards]
    selected_cards = [
        TableCardWithSelection(
            table_card=card,
            selection_reason="Test fixture",
            key_columns=[],
        )
        for card in cards
    ]
    return {
        "user_query": user_query,
        "table_cards_with_selection": selected_cards,
    }


def test_draft_sql_returns_sql_draft(sample_table_card, dummy_settings):
    """Wrap the structured LLM response into an SQLDraft and persist it in workflow state."""
    client = _make_sql_drafter_client(
        sql="SELECT COUNT(DISTINCT SAFETY_REPORT_ID) FROM ICSR.PATIENT WHERE PATIENT_SEX_ID = 1;",
        rationale="Counts unique cases limited to male sex code.",
        tables_used=["ICSR.PATIENT"],
    )
    state = _make_drafter_state("Count male cases by year", sample_table_card)

    result = draft_sql(state, client, dummy_settings.agents.drafter, dummy_settings.target_sql_dialect)

    assert "sql_draft" in result
    sql_draft = result["sql_draft"]

    # Verify the SQLDraft contains the LLM response data
    assert sql_draft.sql.startswith("SELECT COUNT")
    assert "ICSR.PATIENT" in sql_draft.tables_used
    assert sql_draft.rationale == "Counts unique cases limited to male sex code."


def test_draft_sql_formats_prompt(sample_table_card, dummy_settings):
    """Verify prompt structure includes user query and table metadata with correct LLM parameters."""
    client = _make_sql_drafter_client(
        sql="SELECT 1;",
        rationale="noop",
        tables_used=["ICSR.PATIENT"],
    )
    user_query = "Count male cases by year"
    state = _make_drafter_state(user_query, sample_table_card)

    draft_sql(state, client, dummy_settings.agents.drafter, dummy_settings.target_sql_dialect)

    # Verify two-message prompt structure
    assert client.last_messages is not None
    assert len(client.last_messages) == 2

    system_message = client.last_messages[0]
    human_message = client.last_messages[1]

    # Verify prompt content
    assert "SQL Drafting Agent" in system_message.content
    assert "<dialect>" in human_message.content
    assert user_query in human_message.content
    # Verify table card schema and name are in the prompt
    assert '"schema_name": "ICSR"' in human_message.content
    assert '"name": "PATIENT"' in human_message.content
