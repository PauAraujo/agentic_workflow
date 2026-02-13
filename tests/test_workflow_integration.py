import pytest

from typing import Type
from functools import partial
from pydantic import BaseModel
from unittest.mock import patch

from sql_query_assistant.config import Settings
from sql_query_assistant.domain import (
    SQLDraft,
    Column,
    TableCard,
    TableMetadata,
    TableCardWithSelection,
    RetrievalResult,
    TableSelectionResponse,
    TableSelectionDecision,
)
from sql_query_assistant.state import WorkflowState
from sql_query_assistant.workflow.main_graph import build_main_graph


class FakeLLMClient:
    """
    Drop-in replacement for LLMClient that returns pre-configured responses
    without making any network calls.

    The real graph calls client.call_llm() multiple times as it moves through
    nodes, each time requesting a different response schema:

        table_selector  ->  call_llm(schema=TableSelectionResponse)
        sql_drafter     ->  call_llm(schema=SQLDraft)   # 1st SQLDraft call
        sql_repairer    ->  call_llm(schema=SQLDraft)   # 2nd SQLDraft call (if repair needed)

    This fake uses the `schema` argument to decide which canned response to
    return. For SQLDraft specifically, it walks through `sql_responses` in
    order, so the drafter gets the 1st entry, the repairer gets the 2nd, etc.
    """

    def __init__(
        self,
        selector_response: TableSelectionResponse,
        sql_responses: list[SQLDraft],
    ):
        self.selector_response = selector_response
        self.sql_responses = list(sql_responses)
        self.sql_call_index = 0
        self.calls: list[Type[BaseModel]] = []

    def call_llm(self, messages, schema, model_config):
        # `messages` and `model_config` are accepted to match the real signature,
        # but ignored here since responses are pre-configured
        self.calls.append(schema)

        if schema is TableSelectionResponse:
            return self.selector_response

        if schema is SQLDraft:
            # Return sql_responses in order: first call gets [0] (drafter),
            # second call gets [1] (repairer), etc.  If there are more calls
            # than responses, repeat the last one as a safe fallback.
            idx = self.sql_call_index
            self.sql_call_index += 1
            if idx < len(self.sql_responses):
                return self.sql_responses[idx]
            return self.sql_responses[-1]

        raise ValueError(f"FakeLLMClient has no response for {schema.__name__}")


SELECTOR_RESPONSE = TableSelectionResponse(
    rationale="PATIENT table needed for patient query",
    selected_tables=[
        TableSelectionDecision(
            qualified_name="ICSR.PATIENT",
            selection_reason="Contains patient data",
            key_columns=["id", "name"],
        ),
    ],
)


@pytest.fixture
def patient_table_card():
    """A minimal table card matching the test DB's ICSR.PATIENT schema (id, name)."""
    return TableCard(
        table_metadata=TableMetadata(
            qualified_name="ICSR.PATIENT",
            schema_name="ICSR",
            name="PATIENT",
            description="Patient demographics",
            primary_key=["id"],
        ),
        columns=[
            Column(name="id", type="INTEGER", description="Primary key"),
            Column(name="name", type="TEXT", description="Patient name"),
        ],
    )


def _fake_retriever(state: WorkflowState, *, settings, table_card) -> dict:
    """
    Replacement for retrieve_relevant_table_cards that returns a fixed
    table card without calling Azure AI Search.
    """
    return {
        "retrieval_result": RetrievalResult(
            tables_from_search=["ICSR.PATIENT"],
            tables_after_rerank=["ICSR.PATIENT"],
            tables_from_fk_expansion=[],
            tables_final=["ICSR.PATIENT"],
        ),
        "table_cards": [table_card],
        "all_table_cards": [table_card],
    }


def _run_graph(settings: Settings, client, patient_table_card) -> dict:
    """Build the graph with a patched retriever and invoke it."""
    fake_retriever_node = partial(
        _fake_retriever, settings=settings, table_card=patient_table_card
    )
    with patch(
        "sql_query_assistant.workflow.main_graph.retrieve_relevant_table_cards",
        fake_retriever_node,
    ):
        graph = build_main_graph(client=client, settings=settings)
        return graph.invoke({
            "user_query": "Show me all patients",
            "allowed_schemas": ["ICSR"],
        })


def test_happy_path_valid_sql(db_with_patient_table, patient_table_card):
    """
    Full pipeline: retriever -> selector -> drafter -> validator (pass)
    -> executor -> persistence.

    Asserts the final state has all expected fields and the query result
    contains real rows from the test DB.
    """
    settings: Settings = db_with_patient_table
    valid_sql = "SELECT id, name FROM ICSR.PATIENT"

    client = FakeLLMClient(
        selector_response=SELECTOR_RESPONSE,
        sql_responses=[SQLDraft(rationale="Select all patients", sql=valid_sql)],
    )

    final_state = _run_graph(settings, client, patient_table_card)

    # Retrieval stage
    assert final_state["retrieval_result"].tables_final == ["ICSR.PATIENT"]
    assert len(final_state["table_cards"]) == 1

    # Table selection stage
    assert len(final_state["table_cards_with_selection"]) == 1
    selected_table = final_state["table_cards_with_selection"][0]
    assert isinstance(selected_table, TableCardWithSelection)
    assert selected_table.table_card.table_metadata.qualified_name == "ICSR.PATIENT"

    # SQL draft stage
    assert final_state["sql_draft"].sql == valid_sql

    # Validation stage
    assert final_state["validation_result"].is_valid
    assert len(final_state["validation_history"]) == 1

    # Execution stage
    query_result = final_state["query_result"]
    assert query_result.success is True
    assert query_result.row_count == 2
    assert query_result.column_names == ["id", "name"]
    assert {"id": 1, "name": "Alice"} in query_result.rows
    assert {"id": 2, "name": "Bob"} in query_result.rows

    # No repair attempts
    assert final_state.get("repair_attempts", 0) == 0
    assert final_state.get("repair_history", []) == []

    # Persistence stage
    assert final_state.get("run_id") is not None
    assert settings.paths.query_runs_file.exists()
    assert any(settings.paths.state_dumps_dir.glob("run_*.json"))


def test_repair_loop(db_with_patient_table, patient_table_card):
    """
    Drafter produces bad SQL -> validator rejects -> repairer fixes ->
    validator passes -> executor runs.

    Asserts repair_attempts == 1, repair_history is populated, and the
    final query still succeeds.
    """
    settings: Settings = db_with_patient_table

    bad_sql = "SELECT id, name FROM ICSR.NONEXISTENT_TABLE"
    good_sql = "SELECT id, name FROM ICSR.PATIENT"

    client = FakeLLMClient(
        selector_response=SELECTOR_RESPONSE,
        sql_responses=[
            SQLDraft(rationale="First attempt (wrong table)", sql=bad_sql),
            SQLDraft(rationale="Fixed: correct table name", sql=good_sql),
        ],
    )

    final_state = _run_graph(settings, client, patient_table_card)

    # Repair happened
    assert final_state["repair_attempts"] == 1
    assert len(final_state["repair_history"]) == 2  # original + repaired

    # repair_history[0] is the original failed draft
    assert final_state["repair_history"][0].sql == bad_sql
    # repair_history[1] is the repaired draft
    assert final_state["repair_history"][1].sql == good_sql

    # Validation history shows two runs
    assert len(final_state["validation_history"]) == 2
    assert not final_state["validation_history"][0].is_valid  # first: failed
    assert final_state["validation_history"][1].is_valid  # second: passed

    # Final SQL is the repaired version
    assert final_state["sql_draft"].sql == good_sql
    assert final_state["validation_result"].is_valid

    # Execution succeeded
    query_result = final_state["query_result"]
    assert query_result.success is True
    assert query_result.row_count == 2

    # Persistence
    assert final_state.get("run_id") is not None
