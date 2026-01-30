import csv
import json
import re

from sql_query_assistant.persistence.service import save_workflow_results, rebuild_csv_from_json
from sql_query_assistant.persistence import persist_results
from sql_query_assistant.domain import RunRecord


def is_valid_run_id(run_id: str) -> bool:
    """Check if run_id matches format YYYYMMDD_HHMMSS_ffffff."""
    return bool(re.match(r"^\d{8}_\d{6}_\d{6}$", run_id))


def test_save_workflow_results_creates_json_and_csv(dummy_settings, complete_workflow_state):
    """Should create JSON (source of truth) and CSV index with correct content."""
    run_id = save_workflow_results(complete_workflow_state, dummy_settings)
    assert is_valid_run_id(run_id)

    # JSON has correct structure
    json_file = dummy_settings.paths.state_dumps_dir / f"run_{run_id}.json"
    data = json.loads(json_file.read_text())
    assert data["run_id"] == run_id
    assert "timestamp" in data  # ISO format timestamp is present
    assert data["user_query"] == "Show me all patients"
    assert data["config"]["target_sql_dialect"] == "sqlite"
    assert data["drafting_and_validation"]["final_sql"] == "SELECT * FROM ICSR.PATIENT"
    assert data["execution"]["succeeded"] is True

    # CSV has matching row with all expected fields
    csv_file = dummy_settings.paths.query_runs_file
    with open(csv_file, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["run_id"] == run_id
    assert set(rows[0].keys()) == set(RunRecord.CSV_FIELDNAMES)


def test_save_workflow_results_appends_to_csv(dummy_settings, complete_workflow_state):
    """Multiple saves should append to CSV without duplicate headers."""
    save_workflow_results(complete_workflow_state, dummy_settings)
    save_workflow_results(complete_workflow_state, dummy_settings)

    lines = dummy_settings.paths.query_runs_file.read_text().strip().split("\n")
    assert len(lines) == 3  # header + 2 rows


def test_rebuild_csv_from_json(dummy_settings, complete_workflow_state):
    """Should rebuild CSV index from JSON files."""
    run_id_1 = save_workflow_results(complete_workflow_state, dummy_settings)
    run_id_2 = save_workflow_results(complete_workflow_state, dummy_settings)

    # Delete CSV, rebuild from JSON
    dummy_settings.paths.query_runs_file.unlink()
    count = rebuild_csv_from_json(dummy_settings)

    assert count == 2
    with open(dummy_settings.paths.query_runs_file, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    assert [r["run_id"] for r in rows] == sorted([run_id_1, run_id_2])


def test_rebuild_csv_handles_empty_state(dummy_settings):
    """Should handle missing/empty JSON directory gracefully."""
    assert rebuild_csv_from_json(dummy_settings) == 0


def test_persist_results_returns_run_id(dummy_settings, complete_workflow_state):
    """Workflow node should return valid run_id."""
    result = persist_results(complete_workflow_state, dummy_settings)
    assert is_valid_run_id(result["run_id"])


def test_persist_results_skips_without_sql_draft(dummy_settings, complete_workflow_state):
    """Should skip persistence when sql_draft is missing."""
    state = {**complete_workflow_state, "sql_draft": None}
    assert persist_results(state, dummy_settings) == {}
