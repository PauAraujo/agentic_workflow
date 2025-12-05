import csv
import json
import pytest

from sql_query_assistant.modules.persistence.service import (
    _get_next_run_id,
    _append_to_csv,
    save_workflow_results,
    save_full_state_json,
)


def test_get_next_run_id_returns_1_when_file_missing(tmp_path):
    """Return 1 when CSV file doesn't exist."""
    non_existent_file = tmp_path / "query_runs.csv"
    assert _get_next_run_id(non_existent_file) == 1


def test_get_next_run_id_returns_1_when_file_empty(tmp_path):
    """Return 1 when CSV file exists but is empty."""
    empty_file = tmp_path / "query_runs.csv"
    empty_file.write_text("")
    assert _get_next_run_id(empty_file) == 1


def test_get_next_run_id_returns_max_plus_one(tmp_path):
    """Return max existing ID + 1 when CSV has valid run IDs."""
    csv_file = tmp_path / "query_runs.csv"
    csv_file.write_text("run_id,timestamp,user_query\n1,2024-01-01,query1\n3,2024-01-02,query2\n")

    assert _get_next_run_id(csv_file) == 4


def test_get_next_run_id_raises_on_corrupted_csv(tmp_path):
    """Raise RuntimeError when CSV is corrupted and cannot be read."""
    csv_file = tmp_path / "query_runs.csv"
    csv_file.write_text("run_id,timestamp\n1,2024-01-01\nBAD_DATA")

    with pytest.raises(RuntimeError, match="Failed to read existing run IDs"):
        _get_next_run_id(csv_file)


def test_append_to_csv_creates_file_with_headers(tmp_path):
    """Create new CSV file with headers on first write."""
    csv_file = tmp_path / "test.csv"
    row = {"id": 1, "name": "test"}
    fieldnames = ["id", "name"]

    _append_to_csv(csv_file, row, fieldnames)

    content = csv_file.read_text()
    assert "id,name" in content
    assert "1,test" in content


def test_append_to_csv_appends_without_duplicate_headers(tmp_path):
    """Append to existing CSV without duplicating headers."""
    csv_file = tmp_path / "test.csv"
    fieldnames = ["id", "name"]

    _append_to_csv(csv_file, {"id": 1, "name": "first"}, fieldnames)
    _append_to_csv(csv_file, {"id": 2, "name": "second"}, fieldnames)

    lines = csv_file.read_text().strip().split("\n")
    assert len(lines) == 3  # header + 2 data rows
    assert lines[0] == "id,name"


def test_append_to_csv_raises_on_missing_keys(tmp_path):
    """Raise ValueError when row is missing required fields."""
    csv_file = tmp_path / "test.csv"
    row = {"id": 1}  # Missing 'name'
    fieldnames = ["id", "name"]

    with pytest.raises(ValueError, match="CSV schema mismatch.*Missing keys"):
        _append_to_csv(csv_file, row, fieldnames)


def test_append_to_csv_raises_on_extra_keys(tmp_path):
    """Raise ValueError when row has unexpected extra fields."""
    csv_file = tmp_path / "test.csv"
    row = {"id": 1, "name": "test", "extra": "unexpected"}
    fieldnames = ["id", "name"]

    with pytest.raises(ValueError, match="CSV schema mismatch.*Extra keys"):
        _append_to_csv(csv_file, row, fieldnames)


def test_save_workflow_results_creates_both_csv_files(dummy_settings, complete_workflow_state):
    """Create query_runs.csv and query_assumptions.csv with correct data."""
    run_id = save_workflow_results(complete_workflow_state, dummy_settings)

    # Check run_id is assigned
    assert run_id == 1

    # Check query_runs.csv exists and has correct structure
    query_runs_file = dummy_settings.paths.query_runs_file
    assert query_runs_file.exists()

    with open(query_runs_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["run_id"] == "1"
        assert rows[0]["user_query"] == "Show me all patients"
        assert rows[0]["sql"] == "SELECT * FROM ICSR.PATIENT"

    # Check query_assumptions.csv exists and has correct structure
    query_assumptions_file = dummy_settings.paths.query_assumptions_file
    assert query_assumptions_file.exists()

    with open(query_assumptions_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["run_id"] == "1"
        assert rows[0]["assumption_id"] == "sex_logic"
        assert rows[0]["selected_value"] == "INCLUDE_UNKNOWN"


def test_save_workflow_results_handles_no_assumptions(dummy_settings, complete_workflow_state):
    """Handle workflow state with no assumptions gracefully."""
    # Remove assumptions
    complete_workflow_state["intent_card"].assumption_response.assumption_choices = []

    run_id = save_workflow_results(complete_workflow_state, dummy_settings)

    assert run_id == 1

    # query_runs.csv should still be created
    assert dummy_settings.paths.query_runs_file.exists()

    # query_assumptions.csv should be empty (only headers)
    query_assumptions_file = dummy_settings.paths.query_assumptions_file
    if query_assumptions_file.exists():
        content = query_assumptions_file.read_text()
        lines = [line for line in content.strip().split("\n") if line]
        # Should only have header row if file exists
        assert len(lines) <= 1


def test_save_full_state_json_creates_valid_json(dummy_settings, complete_workflow_state):
    """Create state JSON file with correct structure and all fields."""
    run_id = 1
    save_full_state_json(complete_workflow_state, dummy_settings, run_id)

    json_file = dummy_settings.paths.state_dumps_dir / "run_00001.json"
    assert json_file.exists()

    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Verify structure
    assert data["user_query"] == "Show me all patients"
    assert isinstance(data["table_cards"], list)
    assert isinstance(data["assumption_catalog"], list)
    assert isinstance(data["intent_card"], dict)
    assert isinstance(data["sql_draft"], dict)
    assert data["sql_draft"]["sql"] == "SELECT * FROM ICSR.PATIENT"


def test_save_full_state_json_handles_missing_optional_fields(dummy_settings, complete_workflow_state):
    """Handle state with missing optional fields gracefully."""
    # Remove optional field
    del complete_workflow_state["selected_assumptions"]

    run_id = 1
    save_full_state_json(complete_workflow_state, dummy_settings, run_id)

    json_file = dummy_settings.paths.state_dumps_dir / "run_00001.json"
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Should serialize with empty list for missing field
    assert data["selected_assumptions"] == []