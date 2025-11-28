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
    "sql_rationale",
    "tables_used",
    "deployment_name",
]
QUERY_ASSUMPTIONS_FIELDNAMES = [
    RUN_ID_COLUMN,
    "assumption_id",
    "assumption_label",
    "selected_value",
    "selected_label",
    "rationale",
]
JSON_FILENAME_PATTERN = "run_{:05d}.json"



def _ensure_output_dir(output_dir: Path) -> None:
    """
    Create output directory if it doesn't exist.

    Args:
        output_dir: Path to the output directory
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.debug("Output directory ensured: %s", output_dir)


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
        logger.warning("Could not read existing run IDs: %s. Starting from 1.", e)
        return 1


def _append_to_csv(file_path: Path, row: dict[str, Any], fieldnames: list[str]) -> None:
    """
    Append a row to a CSV file, creating it with headers if it doesn't exist.

    Args:
        file_path: Path to the CSV file
        row: Dictionary containing the row data
        fieldnames: List of column names for the CSV

    Raises:
        ValueError: If row keys don't match fieldnames exactly
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

    with open(file_path, 'a', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def save_workflow_results(state: WorkflowState, settings: Settings) -> int:
    """
    Save workflow results as normalized CSVs.

    Creates two CSV files:
    - One for query runs
    - One for associated assumptions

    Args:
        state: Complete workflow state after execution
        settings: Settings instance containing output_dir path

    Returns:
        The run_id assigned to this execution
    """
    output_dir = settings.paths.output_dir
    _ensure_output_dir(output_dir)

    query_runs_file = settings.paths.query_runs_file
    query_assumptions_file = settings.paths.query_assumptions_file

    # Get next run ID
    run_id = _get_next_run_id(query_runs_file)
    timestamp = datetime.now().isoformat()

    # Extract data from state
    intent_card = state.get("intent_card")
    sql_draft = state.get("sql_draft")

    if not intent_card or not sql_draft:
        logger.warning("Missing intent_card or sql_draft in state. Skipping save.")
        return run_id

    # Save query run
    query_run_row = {
        RUN_ID_COLUMN: run_id,
        "timestamp": timestamp,
        "user_query": state["user_query"],
        "sql": sql_draft.sql,
        "sql_rationale": sql_draft.rationale,
        "tables_used": json.dumps(sql_draft.tables_used),
        "deployment_name": settings.azure.default_deployment_name,
    }

    _append_to_csv(query_runs_file, query_run_row, QUERY_RUNS_FIELDNAMES)
    logger.info("Saved query run #%d to %s", run_id, query_runs_file)

    # Save assumptions
    assumptions = intent_card.assumption_response.assumption_choices
    if assumptions:
        for assumption in assumptions:
            assumption_row = {
                RUN_ID_COLUMN: run_id,
                "assumption_id": assumption.assumption_id,
                "assumption_label": assumption.assumption_label or "",
                "selected_value": assumption.selected_value,
                "selected_label": assumption.selected_label or "",
                "rationale": assumption.rationale,
            }
            _append_to_csv(query_assumptions_file, assumption_row, QUERY_ASSUMPTIONS_FIELDNAMES)

        logger.info("Saved %d assumptions to %s", len(assumptions), query_assumptions_file)
    else:
        logger.info("No assumptions to save for run #%d", run_id)

    return run_id


def save_full_state_json(state: WorkflowState, settings: Settings, run_id: int) -> None:
    """
    Save the complete workflow state as JSON for exact reproduction.

    Args:
        state: Complete workflow state after execution
        settings: Settings instance containing output_dir path
        run_id: The run ID for this execution
    """
    output_dir = settings.paths.output_dir
    _ensure_output_dir(output_dir)

    json_dir = settings.paths.state_dumps_dir
    # Use parents=True to allow nested subdir overrides (e.g., "runs/state_dumps")
    json_dir.mkdir(parents=True, exist_ok=True)

    json_file = json_dir / JSON_FILENAME_PATTERN.format(run_id)

    # Convert state to serializable format
    serializable_state = {
        "user_query": state["user_query"],
        "table_cards": [card.model_dump() for card in state["table_cards"]],
        "assumption_catalog": [entry.model_dump() for entry in state["assumption_catalog"]],
        "selected_assumptions": [assum.model_dump() for assum in state.get("selected_assumptions", [])],
        "intent_card": state["intent_card"].model_dump() if state.get("intent_card") else None,
        "sql_draft": state["sql_draft"].model_dump() if state.get("sql_draft") else None,
    }

    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(serializable_state, f, indent=2, ensure_ascii=False)

    logger.info("Saved full state JSON to %s", json_file)
