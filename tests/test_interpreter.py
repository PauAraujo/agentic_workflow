from typing import cast

import pytest

from sql_query_assistant.domain import SelectedAssumption
from sql_query_assistant.llm_client import OpenAILLMClient
from sql_query_assistant.modules.interpreter.models import RawAssumptionSelection, RawInterpreterResponse
from sql_query_assistant.modules.interpreter.nodes import build_intent_card, interpret_query


class DummyLLMClient:
    """Fakes OpenAILLMClient.call_llm to avoid network calls."""

    def __init__(self, response):
        self.response = response
        self.call_count = 0
        self.last_schema = None
        self.last_deployment_name = None
        self.last_temperature = None

    def call_llm(self, messages, schema, deployment_name=None, temperature=0.0):
        self.call_count += 1
        self.last_schema = schema
        self.last_deployment_name = deployment_name
        self.last_temperature = temperature

        if self.response is not None and not isinstance(self.response, schema):
            raise TypeError(f"Response type {type(self.response)} does not match schema {schema}")

        return self.response


@pytest.fixture
def user_query():
    return "Count adult male patients from 2023"


def test_interpret_query_enriches_from_catalog(sample_table_card, sample_assumption_catalog, user_query):
    """Interpreter should enrich selections with catalog metadata and selected flags."""
    llm_response = RawInterpreterResponse(
        assumptions=[
            RawAssumptionSelection(
                id="age_logic",
                option_value="REPORTED_GROUP",
                rationale="Query mentions adult, so stick to reported age groups",
            )
        ]
    )
    client = cast(OpenAILLMClient, DummyLLMClient(llm_response))

    state = {
        "user_query": user_query,
        "table_cards": [sample_table_card],
        "assumption_catalog": sample_assumption_catalog,
    }

    result = interpret_query(state, client)
    selected = result["selected_assumptions"][0]

    assert client.call_count == 1
    assert client.last_schema is RawInterpreterResponse
    assert client.last_deployment_name == "gpt-4o-mini"
    assert client.last_temperature == pytest.approx(0.0)

    assert selected.assumption_label == "Age Selection Method"
    assert selected.selected_value == "REPORTED_GROUP"
    assert selected.selected_label == "Reported age group"
    assert selected.option_description.startswith("Use PATIENT_AGE_GROUP_ID")

    availability = {opt.value: opt.selected for opt in selected.available_options}
    assert availability == {
        "REPORTED_GROUP": True,
        "CALCULATED_YEARS": False,
    }


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
