import pytest
import sqlite3

from sql_query_assistant.config import (
    AzureOpenAISettings,
    DatabaseSettings,
    PathSettings,
    Settings,
)
from sql_query_assistant.domain import (
    TableCard,
    TableMetadata,
    Column,
    SQLDraft,
    TableCardWithSelection,
    ValidationResult,
    QueryResult,
    RetrievalResult,
)


class DummyLLMClient:
    "Fakes UnifiedLLMClient.call_llm to avoid network calls and capture prompt data"

    def __init__(self, response):
        self.response = response
        self.call_count = 0
        self.last_messages = None
        self.last_schema = None
        self.last_model_config = None

    def call_llm(self, messages, schema, model_config):
        self.call_count += 1
        self.last_messages = messages
        self.last_schema = schema
        self.last_model_config = model_config

        if self.response is not None and not isinstance(self.response, schema):
            raise TypeError(
                f"Response type {type(self.response)} does not match schema {schema}"
            )

        return self.response


@pytest.fixture
def dummy_settings(tmp_path):
    """Creates dummy Settings instance for testing, using tmp_path for both input and output."""
    return Settings(
        azure=AzureOpenAISettings(
            openai_endpoint="https://example.openai.azure.com",
            api_key="dummy-key",
            api_version="2024-02-15-preview",
            max_retries=1,
        ),
        langfuse=None,
        database=DatabaseSettings(db_type="sqlite"),
        paths=PathSettings(
            input_dir=tmp_path,
            output_dir=tmp_path,
        ),
    )


@pytest.fixture
def db_with_patient_table(dummy_settings):
    """Create a test database with ICSR schema and PATIENT table with sample data."""
    db_dir = dummy_settings.paths.db_dir
    db_dir.mkdir(parents=True, exist_ok=True)

    icsr_db_path = db_dir / "ICSR.db"
    conn = sqlite3.connect(icsr_db_path)
    conn.execute("CREATE TABLE PATIENT (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO PATIENT VALUES (1, 'Alice')")
    conn.execute("INSERT INTO PATIENT VALUES (2, 'Bob')")
    conn.commit()
    conn.close()

    return dummy_settings


@pytest.fixture
def sample_table_card():
    """Returns a sample TableCard model based on actual ICSR.PATIENT structure."""
    return TableCard(
        table_metadata=TableMetadata(
            qualified_name="ICSR.PATIENT",
            schema_name="ICSR",
            name="PATIENT",
            synonyms=["Subject", "Case Demographics", "Patient"],
            description="Stores demographic details. Granularity: One row per Safety Report.",
            primary_key=["SAFETY_REPORT_ID"],
        ),
        columns=[
            Column(
                name="SAFETY_REPORT_ID",
                type="NUMBER",
                description="Primary Key. Use for counting distinct cases.",
            ),
            Column(
                name="PATIENT_SEX_ID",
                type="NUMBER",
                description="Coded gender.",
                fk="ICSR_LOOKUP.PATIENT_SEX.PATIENT_SEX_ID",
                value_map_ref="PATIENT_SEX",
            ),
            Column(
                name="PATIENT_AGE_GROUP_ID",
                type="NUMBER",
                description="Coded age group.",
                fk="ICSR_LOOKUP.PATIENT_AGE_GROUP.PATIENT_AGE_GROUP_ID",
                value_map_ref="PATIENT_AGE_GROUP",
            ),
        ],
        value_maps={
            "PATIENT_SEX": {"1": "Male", "2": "Female"},
            "PATIENT_AGE_GROUP": {
                "1": "Neonate",
                "2": "Infant",
                "3": "Child",
                "4": "Adolescent",
                "5": "Adult",
                "6": "Elderly",
            },
        },
    )


@pytest.fixture
def sample_raw_table_card_dict():
    """Returns minimal raw dictionary for testing file loaders."""
    return {
        "table_metadata": {
            "qualified_name": "ICSR.PATIENT",
            "schema_name": "ICSR",
            "name": "PATIENT",
            "synonyms": ["Patient"],
            "description": "Patient demographic data",
            "primary_key": ["SAFETY_REPORT_ID"],
        },
        "columns": [
            {
                "name": "SAFETY_REPORT_ID",
                "type": "NUMBER",
                "description": "Primary Key",
            }
        ],
    }


@pytest.fixture
def complete_workflow_state(sample_table_card):
    """
    Returns a complete WorkflowState with all fields populated.

    Useful for testing persistence module which expects fully executed workflow state.
    """

    selected_table_card = TableCardWithSelection(
        table_card=sample_table_card,
        selection_reason="Contains patient demographics needed for query",
        key_columns=["SAFETY_REPORT_ID", "PATIENT_SEX_ID"],
    )

    sql_draft = SQLDraft(
        sql="SELECT * FROM ICSR.PATIENT",
        rationale="Simple query to return all patient records",
    )

    validation_result = ValidationResult(
        original_sql="SELECT * FROM ICSR.PATIENT",
        syntax_errors=[],
        explain_errors=[],
    )

    query_result = QueryResult(
        success=True,
        row_count=10,
        column_names=["SAFETY_REPORT_ID", "PATIENT_SEX_ID"],
        rows=[{"SAFETY_REPORT_ID": 1, "PATIENT_SEX_ID": 2}],
        execution_time_ms=15.5,
    )

    retrieval_result = RetrievalResult(
        tables_from_search=["ICSR.PATIENT", "ICSR.DRUG", "ICSR.REACTION"],
        tables_after_rerank=["ICSR.PATIENT"],
        tables_from_fk_expansion=[],
        tables_final=["ICSR.PATIENT"],
    )

    return {
        "user_query": "Show me all patients",
        "retrieval_result": retrieval_result,
        "table_cards": [sample_table_card],
        "all_table_cards": [sample_table_card],
        "table_cards_with_selection": [selected_table_card],
        "sql_draft": sql_draft,
        "validation_result": validation_result,
        "validation_history": [validation_result],
        "query_result": query_result,
        "repair_attempts": 0,
        "repair_history": [],
    }
