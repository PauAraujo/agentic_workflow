import json
import yaml
import pytest

from pathlib import Path
from pydantic import ValidationError

from sql_query_assistant.domain import AssumptionCatalogEntry, AssumptionOption
from sql_query_assistant.utils import load_assumption_catalog, load_table_cards


# Table card loader tests =================================================

def test_load_table_cards_reads_json(tmp_path, dummy_settings, sample_raw_table_card_dict):
    """Load a single valid table card JSON file into a fully populated TableCard model."""
    (tmp_path / "patient.json").write_text(json.dumps(sample_raw_table_card_dict))

    cards = load_table_cards(settings=dummy_settings, base_path=tmp_path)

    assert len(cards) == 1

    # Verify table metadata
    assert cards[0].table_metadata.name == "ICSR.PATIENT"
    assert cards[0].table_metadata.synonyms == ["Patient"]
    assert cards[0].table_metadata.description == "Patient demographic data"
    assert cards[0].table_metadata.primary_key == ["SAFETY_REPORT_ID"]

    # Verify columns
    assert len(cards[0].columns) == 1
    assert cards[0].columns[0].name == "SAFETY_REPORT_ID"
    assert cards[0].columns[0].type == "NUMBER"
    assert cards[0].columns[0].description == "Primary Key"


def test_load_table_cards_ignores_non_json_files(tmp_path, dummy_settings, sample_raw_table_card_dict):
    """
    Ignore non JSON files in the directory while still loading available JSON table cards.
    """
    (tmp_path / "valid.json").write_text(json.dumps(sample_raw_table_card_dict))
    (tmp_path / "ignored.txt").write_text("This should be ignored")
    (tmp_path / "also_ignored.yaml").write_text("key: value")

    cards = load_table_cards(settings=dummy_settings, base_path=tmp_path)

    assert len(cards) == 1
    assert cards[0].table_metadata.name == "ICSR.PATIENT"


@pytest.mark.parametrize("invalid_data", [
    pytest.param(
        {"wrong_field": "wrong_value", "another_field": 123},
        id="invalid_schema_structure"
    ),
    pytest.param(
        {"table_metadata": {"name": "TEST"}}, # Missing synonyms, description, etc.
        id="missing_required_fields"
    ),
])
def test_load_table_cards_raises_validation_error(tmp_path, dummy_settings, invalid_data):
    """
    Raise ValidationError when table card JSON does not conform to the TableCard schema.
    """
    (tmp_path / "invalid.json").write_text(json.dumps(invalid_data))

    with pytest.raises(ValidationError):
        load_table_cards(settings=dummy_settings, base_path=tmp_path)


@pytest.mark.parametrize(
    "setup_files, scenario",
    [
        pytest.param(None, "directory_does_not_exist", id="missing-directory"),
        pytest.param({}, "directory_is_empty", id="empty-directory"),
        pytest.param(
            {"readme.txt": "ignore me", "data.yaml": "key: val"},
            "ignores_non_json_extensions",
            id="non-json-only",
        ),
    ],
)
def test_load_table_cards_returns_empty_list(tmp_path, dummy_settings, setup_files, scenario):
    """
    Return an empty list when the cards directory is missing, empty, or contains only non JSON files.
    """
    base_path = tmp_path / "cards"

    if setup_files is not None:
        base_path.mkdir()
        for filename, content in setup_files.items():
            (base_path / filename).write_text(content)
    # If setup_files is None we intentionally leave the directory nonexistent.

    cards = load_table_cards(settings=dummy_settings, base_path=base_path)

    assert cards == [], f"Unexpected cards loaded for scenario: {scenario}"


def test_load_table_cards_malformed_json(tmp_path, dummy_settings):
    """
    Raise JSONDecodeError when a table card JSON file cannot be parsed.
    """
    (tmp_path / "malformed.json").write_text("{invalid json content")

    with pytest.raises(json.JSONDecodeError):
        load_table_cards(settings=dummy_settings, base_path=tmp_path)


def test_load_table_cards_with_extra_fields(tmp_path, dummy_settings, sample_raw_table_card_dict):
    """
    Ignore unexpected top level keys in table card JSON while still constructing TableCard models.
    """
    data_with_extras = sample_raw_table_card_dict.copy()
    data_with_extras["unexpected_field"] = "should be ignored"
    data_with_extras["another_extra"] = 12345

    (tmp_path / "with_extras.json").write_text(json.dumps(data_with_extras))

    cards = load_table_cards(settings=dummy_settings, base_path=tmp_path)

    assert len(cards) == 1
    assert cards[0].table_metadata.name == "ICSR.PATIENT"


# Assumption catalog loader tests  =================================================

def test_load_assumption_catalog_reads_yaml(tmp_path, dummy_settings, sample_raw_assumption_catalog_dict):
    """Load a valid YAML catalog file into AssumptionCatalogEntry and AssumptionOption models."""
    catalog_path = tmp_path / "assumptions.yaml"
    catalog_path.write_text(yaml.safe_dump(sample_raw_assumption_catalog_dict))

    loaded = load_assumption_catalog(settings=dummy_settings, catalog_path=catalog_path)

    # Verify catalog structure
    assert len(loaded) == 1
    assert isinstance(loaded[0], AssumptionCatalogEntry)

    # Verify top-level fields
    entry = loaded[0]
    assert entry.id == "sex_logic"
    assert entry.label == "Gender Inclusion Scope"
    assert entry.description == "Define if analysis is strictly binary or inclusive of unknown data."

    # Verify options structure
    assert len(entry.options) == 2
    assert all(isinstance(opt, AssumptionOption) for opt in entry.options)

    # Verify first option (BINARY_STRICT)
    opt1 = entry.options[0]
    assert opt1.value == "BINARY_STRICT"
    assert opt1.label == "Binary only"
    assert opt1.description == "Only include ID 1 (Male) and 2 (Female)."

    # Verify second option (INCLUDE_UNKNOWN)
    opt2 = entry.options[1]
    assert opt2.value == "INCLUDE_UNKNOWN"
    assert opt2.label == "Include unknown"
    assert opt2.description == "Include Nulls and NullFlavors (UNK, MSK, NASK)."


# Parametrized validation tests for assumption catalog
@pytest.mark.parametrize("invalid_data", [
    pytest.param(
        [{"wrong_field": "wrong_value"}],
        id="invalid_schema_structure"
    ),
    pytest.param(
        [{"id": "test_id", "label": "Test label"}], # Missing description, options
        id="missing_required_fields"
    ),
])
def test_load_assumption_catalog_raises_validation_error(tmp_path, dummy_settings, invalid_data):
    """
    Raise ValidationError when catalog entries do not satisfy the AssumptionCatalogEntry schema.
    """
    catalog_path = tmp_path / "invalid.yaml"
    catalog_path.write_text(yaml.safe_dump(invalid_data))

    with pytest.raises(ValidationError):
        load_assumption_catalog(settings=dummy_settings, catalog_path=catalog_path)


@pytest.mark.parametrize("file_content", [
    pytest.param("", id="empty_string"),
    pytest.param("null", id="explicit_null"),
    pytest.param("# just a comment", id="comment_only"),
])
def test_load_assumption_catalog_returns_empty_list_on_empty_content(
    tmp_path, dummy_settings, file_content
):
    """
    Treat empty, explicit null, or comment only YAML content as an empty assumption catalog.
    """
    catalog_path = tmp_path / "assumptions.yaml"
    catalog_path.write_text(file_content)

    loaded = load_assumption_catalog(settings=dummy_settings, catalog_path=catalog_path)

    assert loaded == []


def test_load_assumption_catalog_missing_file(dummy_settings):
    """
    Raise FileNotFoundError when the catalog_path does not point to an existing file.
    """
    nonexistent_file = Path("/nonexistent/catalog.yaml")

    with pytest.raises(FileNotFoundError):
        load_assumption_catalog(settings=dummy_settings, catalog_path=nonexistent_file)


def test_load_assumption_catalog_malformed_yaml(tmp_path, dummy_settings):
    """
    Raise YAMLError when the catalog YAML is syntactically invalid and cannot be parsed.
    """
    catalog_path = tmp_path / "malformed.yaml"
    catalog_path.write_text("invalid: yaml: content: [")

    with pytest.raises(yaml.YAMLError):
        load_assumption_catalog(settings=dummy_settings, catalog_path=catalog_path)


def test_load_assumption_catalog_with_extra_fields(tmp_path, dummy_settings, sample_raw_assumption_catalog_dict):
    """
    Ignore unexpected keys in catalog entries while still constructing AssumptionCatalogEntry models.
    """
    data_with_extras = sample_raw_assumption_catalog_dict.copy()
    data_with_extras[0]["unexpected_field"] = "should be ignored"

    catalog_path = tmp_path / "with_extras.yaml"
    catalog_path.write_text(yaml.safe_dump(data_with_extras))

    loaded = load_assumption_catalog(settings=dummy_settings, catalog_path=catalog_path)

    assert len(loaded) == 1
    assert loaded[0].id == "sex_logic"

