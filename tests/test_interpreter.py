import pytest

from typing import cast

from tests.conftest import DummyLLMClient
from sql_query_assistant.domain import (
    AssumptionCatalogEntry,
    AssumptionOption,
    SelectedAssumption,
)
from sql_query_assistant.llm_client import OpenAILLMClient
from sql_query_assistant.modules.interpreter.models import RawAssumptionSelection, RawInterpreterResponse
from sql_query_assistant.modules.interpreter.nodes import build_intent_card, interpret_query


def _make_llm_client(assumption_selections):
    """Create a DummyLLMClient with the given assumption selections."""
    llm_response = RawInterpreterResponse(assumptions=assumption_selections)
    return cast(OpenAILLMClient, DummyLLMClient(llm_response))


def _make_interpreter_state(user_query, table_cards, assumption_catalog):
    """Build a standard workflow state dict for interpreter tests."""
    return {
        "user_query": user_query,
        "table_cards": table_cards if isinstance(table_cards, list) else [table_cards],
        "assumption_catalog": assumption_catalog,
    }


@pytest.fixture
def user_query():
    return "Count adult male patients from 2023"


def test_interpret_query_enriches_from_catalog(sample_table_card, sample_assumption_catalog, user_query):
    """Interpreter should enrich selections with catalog metadata and selected flags."""
    client = _make_llm_client([
        RawAssumptionSelection(
            id="age_logic",
            option_value="REPORTED_GROUP",
            rationale="Query mentions adult, so stick to reported age groups",
        )
    ])
    interpreter_state = _make_interpreter_state(user_query, sample_table_card, sample_assumption_catalog)

    result = interpret_query(interpreter_state, client)
    selected = result["selected_assumptions"][0]

    # Verify LLM call parameters
    assert client.call_count == 1
    assert client.last_schema is RawInterpreterResponse
    assert client.last_deployment_name == "gpt-4o-mini"
    assert client.last_temperature == pytest.approx(0.0)

    # Verify enrichment from catalog
    assert selected.assumption_label == "Age Selection Method"
    assert selected.selected_value == "REPORTED_GROUP"
    assert selected.selected_label == "Reported age group"
    assert selected.option_description.startswith("Use PATIENT_AGE_GROUP_ID")

    # Verify available options with correct selection flags
    availability = {opt.value: opt.selected for opt in selected.available_options}
    assert availability == {
        "REPORTED_GROUP": True,
        "CALCULATED_YEARS": False,
    }


def test_interpret_query_invalid_option_falls_back_to_default(
    sample_table_card, sample_assumption_catalog, user_query
):
    """Interpreter should guard against invalid option values and use catalog defaults."""
    client = _make_llm_client([
        RawAssumptionSelection(
            id="sex_logic",
            option_value="NOT_IN_CATALOG",  # Not part of the catalog options
            rationale="Model hallucinated an option value",
        )
    ])
    interpreter_state = _make_interpreter_state(user_query, sample_table_card, sample_assumption_catalog)

    result = interpret_query(interpreter_state, client)
    selected = result["selected_assumptions"][0]

    # Should fall back to catalog default (BINARY_STRICT)
    assert selected.assumption_label == "Gender Inclusion Scope"
    assert selected.selected_value == "BINARY_STRICT"
    assert selected.selected_label == "Binary only"
    assert selected.option_description.startswith("Only include ID 1 (Male) and 2 (Female).")

    # Verify the fallback option is marked as selected
    availability = {opt.value: opt.selected for opt in selected.available_options}
    assert availability == {
        "BINARY_STRICT": True,
        "INCLUDE_UNKNOWN": False,
    }


def test_interpret_query_skips_unknown_assumption(sample_table_card, sample_assumption_catalog, user_query):
    """Unknown assumption IDs from the model should be ignored instead of propagating bad data."""
    client = _make_llm_client([
        RawAssumptionSelection(
            id="made_up_assumption",
            option_value="ANYTHING",
            rationale="Invalid assumption id",
        )
    ])
    interpreter_state = _make_interpreter_state(user_query, sample_table_card, sample_assumption_catalog)

    result = interpret_query(interpreter_state, client)

    # Unknown assumptions should be skipped entirely
    assert result["selected_assumptions"] == []


def test_interpret_query_skips_assumption_with_empty_options(sample_table_card, user_query):
    """Assumptions with empty options list should be skipped as they are malformed."""
    # Create a malformed catalog entry with no options
    malformed_catalog = [
        AssumptionCatalogEntry(
            id="broken_assumption",
            label="Broken Assumption",
            description="This has no options",
            default=None,
            options=[],  # empty options list
        )
    ]

    client = _make_llm_client([
        RawAssumptionSelection(
            id="broken_assumption",
            option_value="ANYTHING",
            rationale="LLM selected an assumption with no options",
        )
    ])
    interpreter_state = _make_interpreter_state(user_query, sample_table_card, malformed_catalog)

    result = interpret_query(interpreter_state, client)

    # Should skip the malformed assumption
    assert result["selected_assumptions"] == []


def test_interpret_query_handles_invalid_default_in_catalog(sample_table_card, user_query):
    """If catalog default doesn't exist in options, should fall back to first option."""
    # Create catalog with invalid default
    catalog_with_bad_default = [
        AssumptionCatalogEntry(
            id="bad_default",
            label="Bad Default Test",
            description="Default value not in options",
            default="NONEXISTENT_VALUE",  # this doesn't exist in options
            options=[
                AssumptionOption(
                    value="VALID_OPTION_1",
                    label="Valid Option 1",
                    description="First valid option",
                ),
                AssumptionOption(
                    value="VALID_OPTION_2",
                    label="Valid Option 2",
                    description="Second valid option",
                ),
            ],
        )
    ]

    client = _make_llm_client([
        RawAssumptionSelection(
            id="bad_default",
            option_value="INVALID_SELECTION",  # LLM picks invalid option
            rationale="Testing fallback with bad catalog default",
        )
    ])
    interpreter_state = _make_interpreter_state(user_query, sample_table_card, catalog_with_bad_default)

    result = interpret_query(interpreter_state, client)
    selected = result["selected_assumptions"][0]

    # Should fall back to first option since default is invalid
    assert selected.selected_value == "VALID_OPTION_1"
    assert selected.selected_label == "Valid Option 1"


def test_build_intent_card_wraps_selected_assumptions(user_query):
    """Ensure the intent card carries the user task and selected assumptions."""
    selected = SelectedAssumption(
        assumption_id="age_logic",
        assumption_label="Age Selection Method",
        selected_value="REPORTED_GROUP",
        selected_label="Reported age group",
        option_description="Use PATIENT_AGE_GROUP_ID. Best for terms like 'Adult', 'Child', 'Elderly'.",
        rationale="Query mentions adult",
        available_options=None,
    )
    state = {"user_query": user_query, "selected_assumptions": [selected]}

    result = build_intent_card(state)
    intent = result["intent_card"]

    assert intent.task == user_query
    assert intent.assumption_response.assumption_choices == [selected]
