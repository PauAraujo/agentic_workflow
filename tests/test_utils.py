import json
import pytest

from pydantic import ValidationError

from sql_query_assistant.utils import load_table_cards


def test_load_table_cards_reads_json(
    tmp_path, dummy_settings, sample_raw_table_card_dict
):
    """Load a single valid table card JSON file into a fully populated TableCard model."""
    schema_dir = tmp_path / "ICSR"
    schema_dir.mkdir()
    (schema_dir / "patient.json").write_text(json.dumps(sample_raw_table_card_dict))

    cards = load_table_cards(settings=dummy_settings, base_path=tmp_path)

    assert len(cards) == 1

    # Verify table metadata
    assert cards[0].table_metadata.schema_name == "ICSR"
    assert cards[0].table_metadata.name == "PATIENT"
    assert cards[0].table_metadata.qualified_name == "ICSR.PATIENT"
    assert cards[0].table_metadata.synonyms == ["Patient"]
    assert cards[0].table_metadata.description == "Patient demographic data"
    assert cards[0].table_metadata.primary_key == ["SAFETY_REPORT_ID"]

    # Verify columns
    assert len(cards[0].columns) == 1
    assert cards[0].columns[0].name == "SAFETY_REPORT_ID"
    assert cards[0].columns[0].type == "NUMBER"
    assert cards[0].columns[0].description == "Primary Key"


def test_load_table_cards_ignores_non_json_files(
    tmp_path, dummy_settings, sample_raw_table_card_dict
):
    """
    Ignore non JSON files in the directory while still loading available JSON table cards.
    """
    schema_dir = tmp_path / "ICSR"
    schema_dir.mkdir()
    (schema_dir / "valid.json").write_text(json.dumps(sample_raw_table_card_dict))
    (schema_dir / "ignored.txt").write_text("This should be ignored")
    (schema_dir / "also_ignored.yaml").write_text("key: value")

    cards = load_table_cards(settings=dummy_settings, base_path=tmp_path)

    assert len(cards) == 1
    assert cards[0].table_metadata.qualified_name == "ICSR.PATIENT"


@pytest.mark.parametrize(
    "invalid_data",
    [
        pytest.param(
            {"wrong_field": "wrong_value", "another_field": 123},
            id="invalid_schema_structure",
        ),
        pytest.param({"table_metadata": {}}, id="missing_required_fields"),
    ],
)
def test_load_table_cards_raises_validation_error(
    tmp_path, dummy_settings, invalid_data
):
    """
    Raise ValidationError when table card JSON does not conform to the TableCard schema.
    """
    schema_dir = tmp_path / "TEST_SCHEMA"
    schema_dir.mkdir()
    (schema_dir / "invalid.json").write_text(json.dumps(invalid_data))

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
def test_load_table_cards_returns_empty_list(
    tmp_path, dummy_settings, setup_files, scenario
):
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
    schema_dir = tmp_path / "TEST_SCHEMA"
    schema_dir.mkdir()
    (schema_dir / "malformed.json").write_text("{invalid json content")

    with pytest.raises(json.JSONDecodeError):
        load_table_cards(settings=dummy_settings, base_path=tmp_path)


def test_load_table_cards_with_extra_fields(
    tmp_path, dummy_settings, sample_raw_table_card_dict
):
    """
    Ignore unexpected top level keys in table card JSON while still constructing TableCard models.
    """
    data_with_extras = sample_raw_table_card_dict.copy()
    data_with_extras["unexpected_field"] = "should be ignored"
    data_with_extras["another_extra"] = 12345

    schema_dir = tmp_path / "ICSR"
    schema_dir.mkdir()
    (schema_dir / "with_extras.json").write_text(json.dumps(data_with_extras))

    cards = load_table_cards(settings=dummy_settings, base_path=tmp_path)

    assert len(cards) == 1
    assert cards[0].table_metadata.qualified_name == "ICSR.PATIENT"
