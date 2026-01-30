import pytest

from typing import cast

from tests.conftest import DummyLLMClient
from sql_query_assistant.llm_client import LLMClient
from sql_query_assistant.domain import SQLDraft, ValidationResult
from sql_query_assistant.modules.sql_repairer.nodes import repair_sql


def _make_repair_client(sql, rationale, tables_used):
    """Create a DummyLLMClient with a SQL repair response."""
    llm_response = SQLDraft(
        sql=sql,
        rationale=rationale,
        tables_used=tables_used,
    )
    return cast(LLMClient, DummyLLMClient(llm_response))


def _make_repairer_state(sql_draft, validation_result, user_query, table_cards, repair_attempts=0):
    """Build a standard workflow state dict for repairer tests."""
    return {
        "sql_draft": sql_draft,
        "validation_result": validation_result,
        "user_query": user_query,
        "table_cards": table_cards if isinstance(table_cards, list) else [table_cards],
        "repair_attempts": repair_attempts,
        "repair_history": [],
    }


@pytest.fixture
def failed_validation():
    """Returns a ValidationResult indicating failure."""
    return ValidationResult(
        original_sql="SELECT * FROM WRONG_TABLE",
        syntax_errors=[],
        explain_errors=["no such table: WRONG_TABLE"],
    )


def test_repair_sql_returns_new_sql_draft(
    sample_table_card, failed_validation, dummy_settings
):
    """Repairer should return a new SQLDraft with repaired SQL."""
    original_draft = SQLDraft(
        sql="SELECT * FROM WRONG_TABLE",
        rationale="Original SQL with error",
        tables_used=["WRONG_TABLE"],
    )

    client = _make_repair_client(
        sql="SELECT * FROM PATIENT",
        rationale="Fixed table name from WRONG_TABLE to PATIENT",
        tables_used=["PATIENT"],
    )

    state = _make_repairer_state(
        original_draft, failed_validation, "Count all patients", sample_table_card
    )

    result = repair_sql(state, client, dummy_settings.agents.repairer, dummy_settings.target_sql_dialect, dummy_settings.max_repair_attempts)

    assert "sql_draft" in result
    new_draft = result["sql_draft"]

    # Verify the repaired SQL is different
    assert new_draft.sql == "SELECT * FROM PATIENT"
    assert new_draft.rationale == "Fixed table name from WRONG_TABLE to PATIENT"
    assert new_draft.tables_used == ["PATIENT"]


def test_repair_sql_increments_repair_attempts(
    sample_table_card, failed_validation, dummy_settings
):
    """Repairer should increment repair_attempts counter."""
    original_draft = SQLDraft(
        sql="SELECT * FROM WRONG_TABLE",
        rationale="Error",
        tables_used=["WRONG_TABLE"],
    )

    client = _make_repair_client(
        sql="SELECT * FROM PATIENT",
        rationale="Fixed",
        tables_used=["PATIENT"],
    )

    # Start with repair_attempts = 1
    state = _make_repairer_state(
        original_draft, failed_validation, "Count all patients", sample_table_card, repair_attempts=1
    )

    result = repair_sql(state, client, dummy_settings.agents.repairer, dummy_settings.target_sql_dialect, dummy_settings.max_repair_attempts)

    # Should be incremented to 2
    assert result["repair_attempts"] == 2


def test_repair_sql_tracks_repair_history(
    sample_table_card, failed_validation, dummy_settings
):
    """Repairer should preserve original draft and append repair to history."""
    original_draft = SQLDraft(
        sql="SELECT * FROM WRONG_TABLE",
        rationale="Error",
        tables_used=["WRONG_TABLE"],
    )

    client = _make_repair_client(
        sql="SELECT * FROM PATIENT",
        rationale="Fixed",
        tables_used=["PATIENT"],
    )

    state = _make_repairer_state(
        original_draft, failed_validation, "Count all patients", sample_table_card
    )

    result = repair_sql(state, client, dummy_settings.agents.repairer, dummy_settings.target_sql_dialect, dummy_settings.max_repair_attempts)

    assert "repair_history" in result
    history = result["repair_history"]

    # Should have two entries: original draft + repaired SQL
    assert len(history) == 2

    # First entry should be the original draft (preserved for audit trail)
    assert history[0].sql == "SELECT * FROM WRONG_TABLE"
    assert history[0].rationale == "Error"

    # Second entry should be the repaired SQL
    assert history[1].sql == "SELECT * FROM PATIENT"
    assert history[1].rationale == "Fixed"


def test_repair_sql_uses_validation_errors_in_prompt(
    sample_table_card, failed_validation, dummy_settings
):
    """Repairer should pass validation errors to LLM for context."""
    original_draft = SQLDraft(
        sql="SELECT * FROM WRONG_TABLE",
        rationale="Error",
        tables_used=["WRONG_TABLE"],
    )

    client = _make_repair_client(
        sql="SELECT * FROM PATIENT",
        rationale="Fixed",
        tables_used=["PATIENT"],
    )

    state = _make_repairer_state(
        original_draft, failed_validation, "Count all patients", sample_table_card
    )

    repair_sql(state, client, dummy_settings.agents.repairer, dummy_settings.target_sql_dialect, dummy_settings.max_repair_attempts)

    # Verify the prompt includes validation errors
    assert client.call_count == 1
    assert client.last_messages is not None

    # Check that validation errors appear in the prompt
    user_message = client.last_messages[1].content
    assert "WRONG_TABLE" in user_message
    assert "validation errors" in user_message.lower() or "explain errors" in user_message.lower()


def test_repair_sql_handles_missing_required_state(dummy_settings):
    """Should return empty dict when required state fields are missing."""
    # Missing validation_result
    incomplete_state = {
        "sql_draft": SQLDraft(sql="SELECT 1", rationale="test", tables_used=[]),
        "user_query": "test query",
    }

    client = _make_repair_client(sql="SELECT 1", rationale="", tables_used=[])

    result = repair_sql(incomplete_state, client, dummy_settings.agents.repairer, dummy_settings.target_sql_dialect, dummy_settings.max_repair_attempts)

    # Should return empty dict when state is incomplete
    assert result == {}


def test_repair_sql_preserves_history_on_llm_failure(
    sample_table_card, failed_validation, dummy_settings
):
    """Should preserve repair history even if LLM call fails."""
    original_draft = SQLDraft(
        sql="SELECT * FROM WRONG_TABLE",
        rationale="Error",
        tables_used=["WRONG_TABLE"],
    )

    # Create a client that will raise an exception
    class FailingLLMClient:
        def call_llm(self, **kwargs):
            raise RuntimeError("LLM API error")

    client = cast(LLMClient, FailingLLMClient())

    # Pre-populate repair history
    existing_history = [
        SQLDraft(sql="SELECT * FROM ATTEMPT1", rationale="First try", tables_used=["ATTEMPT1"])
    ]

    state = _make_repairer_state(
        original_draft, failed_validation, "Count all patients", sample_table_card, repair_attempts=1
    )
    state["repair_history"] = existing_history

    result = repair_sql(state, client, dummy_settings.agents.repairer, dummy_settings.target_sql_dialect, dummy_settings.max_repair_attempts)

    # Should still increment attempts and preserve history
    assert result["repair_attempts"] == 2
    assert result["repair_history"] == existing_history
