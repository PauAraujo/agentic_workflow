import csv
import json
import logging

from typing import Any
from pathlib import Path
from datetime import datetime

from sql_query_assistant.config import Settings
from sql_query_assistant.domain import RunRecord
from sql_query_assistant.state import WorkflowState

logger = logging.getLogger(__name__)

JSON_FILENAME_PATTERN = "run_{}.json"


def _append_to_csv(file_path: Path, row: dict[str, Any], fieldnames: list[str]) -> None:
    """
    Append a row to a CSV file, creating it with headers if it doesn't exist.

    Args:
        file_path: Path to the CSV file
        row: Dictionary containing the row data
        fieldnames: List of column names for the CSV

    Raises:
        ValueError: If row keys don't match fieldnames exactly
        OSError: If file write fails
    """
    row_keys, expected_keys = set(row.keys()), set(fieldnames)
    if row_keys != expected_keys:
        missing, extra = expected_keys - row_keys, row_keys - expected_keys
        raise ValueError(
            f"CSV schema mismatch for {file_path.name} - missing: {missing}, extra: {extra}"
        )

    file_exists = file_path.exists()
    with open(file_path, 'a', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def save_workflow_results(state: WorkflowState, settings: Settings) -> str:
    """
    Save workflow results with JSON as the source of truth.

    The flow is:
    1. Generate timestamp-based run_id
    2. Build RunRecord from state
    3. Write JSON first (source of truth)
    4. Derive CSV row from RunRecord
    5. Append to CSV (index)

    Args:
        state: Complete workflow state after execution
        settings: Settings instance containing output_dir path

    Returns:
        The run_id assigned to this execution (format: YYYYMMDD_HHMMSS_ffffff)
    """
    # Create output directories
    json_dir = settings.paths.state_dumps_dir
    json_dir.mkdir(parents=True, exist_ok=True)

    # Generate run_id and timestamp from single datetime for consistency
    now = datetime.now()
    run_id = now.strftime("%Y%m%d_%H%M%S_%f")
    timestamp = now.isoformat()

    # Build RunRecord from state
    try:
        run_record = RunRecord.from_state(state, settings, run_id, timestamp)
    except Exception as exc:
        logger.error(f"Failed to build run record: {exc}", exc_info=True)
        raise

    # Write JSON first (source of truth)
    json_file = json_dir / JSON_FILENAME_PATTERN.format(run_id)
    try:
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(run_record.model_dump(), f, indent=2, ensure_ascii=False)
    except TypeError as exc:
        logger.error(f"JSON serialization failed: {exc}", exc_info=True)
        raise
    except OSError as exc:
        raise OSError(f"Failed to write state JSON to {json_file}: {exc}") from exc

    logger.info("Saved full state JSON to %s", json_file)

    # Derive CSV row from RunRecord
    csv_row = run_record.to_csv_row()

    # Append to CSV (index)
    query_runs_file = settings.paths.query_runs_file
    _append_to_csv(query_runs_file, csv_row, RunRecord.CSV_FIELDNAMES)
    logger.info("Saved query run %s to %s", run_id, query_runs_file)

    return run_id


def rebuild_csv_from_json(settings: Settings) -> int:
    """
    Rebuild CSV index from JSON files.

    This utility function regenerates the query_runs.csv file from the
    source-of-truth JSON files in state_dumps_dir. Useful for recovery
    or when the CSV gets out of sync.

    Args:
        settings: Settings instance containing paths

    Returns:
        Number of records processed
    """
    json_dir = settings.paths.state_dumps_dir
    query_runs_file = settings.paths.query_runs_file

    if not json_dir.exists():
        logger.warning("JSON directory does not exist: %s", json_dir)
        return 0

    # Find all JSON files matching the pattern
    json_files = sorted(json_dir.glob("run_*.json"))

    if not json_files:
        logger.info("No JSON files found to rebuild CSV from")
        return 0

    # Remove existing CSV to rebuild fresh
    if query_runs_file.exists():
        query_runs_file.unlink()

    records_processed = 0
    for json_file in json_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            run_record = RunRecord.model_validate(data)
            csv_row = run_record.to_csv_row()
            _append_to_csv(query_runs_file, csv_row, RunRecord.CSV_FIELDNAMES)
            records_processed += 1

        except Exception as exc:
            logger.warning("Failed to process %s: %s", json_file, exc)
            continue

    logger.info("Rebuilt CSV with %d records from JSON files", records_processed)
    return records_processed
