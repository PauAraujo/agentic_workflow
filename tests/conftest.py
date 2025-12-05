import pytest

from sql_query_assistant.config import AzureSettings, PathSettings, Settings
from sql_query_assistant.domain import (
    AssumptionCatalogEntry,
    AssumptionOption,
    TableCard,
    TableMetadata,
    Column,
)


class DummyLLMClient:
    "Fakes OpenAILLMClient.call_llm to avoid network calls and capture prompt data."

    def __init__(self, response):
        self.response = response
        self.call_count = 0
        self.last_messages = None
        self.last_schema = None
        self.last_deployment_name = None
        self.last_temperature = None

    def call_llm(self, messages, schema, deployment_name=None, temperature=0.0):
        self.call_count += 1
        self.last_messages = messages
        self.last_schema = schema
        self.last_deployment_name = deployment_name
        self.last_temperature = temperature

        if self.response is not None and not isinstance(self.response, schema):
            raise TypeError(f"Response type {type(self.response)} does not match schema {schema}")

        return self.response

@pytest.fixture
def dummy_settings(tmp_path):
    """Creates dummy Settings instance for testing, using tmp_path for both input and output."""
    return Settings(
        azure=AzureSettings(
            openai_endpoint="https://example.openai.azure.com",
            api_key="dummy-key",
            api_version="2024-02-15-preview",
            default_deployment_name="gpt-4o-mini",
            max_retries=1,
        ),
        langfuse=None,
        paths=PathSettings(
            input_dir=tmp_path,
            output_dir=tmp_path,  # Use tmp_path for output too!
        ),
    )


@pytest.fixture
def sample_table_card():
    """Returns a sample TableCard model based on actual ICSR.PATIENT structure."""
    return TableCard(
        table_metadata=TableMetadata(
            name="ICSR.PATIENT",
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
                description="Coded gender. FK to PATIENT_SEX.",
            ),
            Column(
                name="PATIENT_AGE_GROUP_ID",
                type="NUMBER",
                description="Coded age group. FK to PATIENT_AGE_GROUP.",
            ),
        ],
    )


@pytest.fixture
def sample_assumption_catalog():
    """Returns a sample assumption catalog with realistic option values."""
    return [
        AssumptionCatalogEntry(
            id="sex_logic",
            label="Gender Inclusion Scope",
            description="Define if analysis is strictly binary or inclusive of unknown data.",
            options=[
                AssumptionOption(
                    value="BINARY_STRICT",
                    label="Binary only",
                    description="Only include ID 1 (Male) and 2 (Female).",
                ),
                AssumptionOption(
                    value="INCLUDE_UNKNOWN",
                    label="Include unknown",
                    description="Include Nulls and NullFlavors (UNK, MSK, NASK).",
                ),
            ],
        ),
        AssumptionCatalogEntry(
            id="age_logic",
            label="Age Selection Method",
            description="Decide whether to use the Reported Group (safer) or Calculated Age (precise).",
            options=[
                AssumptionOption(
                    value="REPORTED_GROUP",
                    label="Reported age group",
                    description="Use PATIENT_AGE_GROUP_ID. Best for terms like 'Adult', 'Child', 'Elderly'.",
                ),
                AssumptionOption(
                    value="CALCULATED_YEARS",
                    label="Calculated age (years)",
                    description="Use ONSET_AGE where Unit is Years. Best for 'Older than 50', 'Between 20 and 30'.",
                ),
            ],
        ),
        AssumptionCatalogEntry(
            id="date_basis",
            label="Temporal Basis",
            description="Which date field drives the timeline.",
            options=[
                AssumptionOption(
                    value="DB_ENTRY",
                    label="Database entry date",
                    description="Use CREATED_ON (System Date).",
                ),
                AssumptionOption(
                    value="EVENT_ONSET",
                    label="Clinical event date",
                    description="Use REACTION.START_DATE (Clinical Date) - Requires Join to REACTION table.",
                ),
            ],
        ),
    ]


@pytest.fixture
def sample_raw_table_card_dict():
    """Returns minimal raw dictionary for testing file loaders."""
    return {
        "table_metadata": {
            "name": "ICSR.PATIENT",
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
def sample_raw_assumption_catalog_dict():
    """Returns minimal raw dictionary for testing file loaders."""
    return [
        {
            "id": "sex_logic",
            "label": "Gender Inclusion Scope",
            "description": "Define if analysis is strictly binary or inclusive of unknown data.",
            "options": [
                {
                    "value": "BINARY_STRICT",
                    "label": "Binary only",
                    "description": "Only include ID 1 (Male) and 2 (Female).",
                },
                {
                    "value": "INCLUDE_UNKNOWN",
                    "label": "Include unknown",
                    "description": "Include Nulls and NullFlavors (UNK, MSK, NASK).",
                },
            ],
        }
    ]
