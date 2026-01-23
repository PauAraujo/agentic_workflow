import csv
import json
import logging

from typing import Any
from pathlib import Path
from datetime import datetime

from sql_query_assistant.config import Settings
from sql_query_assistant.state import WorkflowState

logger = logging.getLogger(__name__)

RUN_ID_COLUMN = "run_id"
QUERY_RUNS_FIELDNAMES = [
    RUN_ID_COLUMN,
    "timestamp",
    "user_query",
    "sql",
    "sql_dialect",
    "sql_rationale",
    "tables_used",
    "deployment_name",
]
JSON_FILENAME_PATTERN = "run_{:05d}.json"


def _get_next_run_id(query_runs_file: Path) -> int:
    """
    Get the next available run ID by reading the existing CSV.

    Args:
        query_runs_file: Path to file storing previous query runs

    Returns:
        Next run ID (1 if file doesn't exist, otherwise max_id + 1)
    """
    if not query_runs_file.exists():
        return 1

    try:
        with open(query_runs_file, 'r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            run_ids = [int(row[RUN_ID_COLUMN]) for row in reader if row.get(RUN_ID_COLUMN)]
            return max(run_ids) + 1 if run_ids else 1
    except Exception as e:
        raise RuntimeError(f"Failed to read existing run IDs from {query_runs_file}: {e}") from e


def _append_to_csv(file_path: Path, row: dict[str, Any], fieldnames: list[str]) -> None:
    """
    Append a row to a CSV file, creating it with headers if it doesn't exist.

    Args:
        file_path: Path to the CSV file
        row: Dictionary containing the row data
        fieldnames: List of column names for the CSV

    Raises:
        ValueError: If row keys don't match fieldnames exactly
        OSError: If file write fails (permissions, disk full, etc.)
    """
    # Validate schema consistency
    row_keys = set(row.keys())
    expected_keys = set(fieldnames)
    if row_keys != expected_keys:
        missing = expected_keys - row_keys
        extra = row_keys - expected_keys
        error_msg = f"CSV schema mismatch for {file_path.name}"
        if missing:
            error_msg += f" - Missing keys: {missing}"
        if extra:
            error_msg += f" - Extra keys: {extra}"
        raise ValueError(error_msg)

    file_exists = file_path.exists()

    try:
        with open(file_path, 'a', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    except OSError as exc:
        raise OSError(f"Failed to write to {file_path}: {exc}") from exc


def save_workflow_results(state: WorkflowState, settings: Settings) -> int:
    """
    Save workflow results to CSV.

    Args:
        state: Complete workflow state after execution
        settings: Settings instance containing output_dir path

    Returns:
        The run_id assigned to this execution
    """
    output_dir = settings.paths.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    query_runs_file = settings.paths.query_runs_file
    sql_draft = state["sql_draft"]
    timestamp = datetime.now().isoformat()

    run_id = _get_next_run_id(query_runs_file)

    query_run_row = {
        RUN_ID_COLUMN: run_id,
        "timestamp": timestamp,
        "user_query": state["user_query"],
        "sql": sql_draft.sql,
        "sql_dialect": sql_draft.dialect,
        "sql_rationale": sql_draft.rationale,
        "tables_used": json.dumps(sql_draft.tables_used),
        "deployment_name": settings.azure.default_deployment_name,
    }

    _append_to_csv(query_runs_file, query_run_row, QUERY_RUNS_FIELDNAMES)
    logger.info("Saved query run #%d to %s", run_id, query_runs_file)

    return run_id


def save_full_state_json(state: WorkflowState, settings: Settings, run_id: int) -> None:
    """
    Save the complete workflow state as JSON for exact reproduction.

    Args:
        state: Complete workflow state after execution
        settings: Settings instance containing output_dir path
        run_id: The run ID for this execution

    Raises:
        OSError: If directory creation or file write fails (permissions, disk full, etc.)
    """
    output_dir = settings.paths.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    json_dir = settings.paths.state_dumps_dir
    json_dir.mkdir(parents=True, exist_ok=True)

    json_file = json_dir / JSON_FILENAME_PATTERN.format(run_id)

    # Convert state to serializable format
    table_cards_with_selection = state.get("table_cards_with_selection", [])
    serializable_state = {
        "user_query": state["user_query"],
        "table_cards_with_selection": [tc.model_dump() for tc in table_cards_with_selection],
        "sql_draft": state["sql_draft"].model_dump() if state.get("sql_draft") else None,
    }

    try:
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(serializable_state, f, indent=2, ensure_ascii=False)
    except OSError as exc:
        raise OSError(f"Failed to write state JSON to {json_file}: {exc}") from exc

    logger.info("Saved full state JSON to %s", json_file)
