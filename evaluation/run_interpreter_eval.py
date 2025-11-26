import argparse
import csv
import logging

from pathlib import Path
from typing import Any, Dict, Iterable
from langchain_core.runnables import Runnable

from sql_query_assistant import (
    WorkflowState,
    build_interpreter_subgraph,
    create_llm_client,
    load_assumption_catalog,
    load_table_cards,
)
from sql_query_assistant.config import Settings

EVAL_DIR = Path(__file__).resolve().parent
GROUND_TRUTH_CSV = EVAL_DIR / "ground_truth_examples.csv"
EXPECTED_ASSUMPTION_IDS = ("age_logic", "sex_logic", "date_basis")

logger = logging.getLogger(__name__)

Expectation = Dict[str, str]
Prediction = Dict[str, str]
ComparisonRow = Dict[str, str | None]
EvalOutcome = Dict[str, Any]


def load_ground_truth(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def normalize_expected(row: dict[str, str]) -> Expectation:
    expected: Expectation = {}
    for key in EXPECTED_ASSUMPTION_IDS:
        value = (row.get(key) or "").strip()
        if value:
            expected[key] = value
    return expected


def normalize_predicted(selected_assumptions: Iterable) -> Prediction:
    predictions: Prediction = {}
    for assumption in selected_assumptions:
        predictions[assumption.assumption_id] = assumption.selected_value
    return predictions


def compare_assumptions(expected: Expectation, predicted: Prediction) -> list[ComparisonRow]:
    comparison: list[ComparisonRow] = []
    for assumption_id in sorted(set(expected) | set(predicted)):
        expected_val = expected.get(assumption_id)
        predicted_val = predicted.get(assumption_id)
        status = "MATCH" if expected_val == predicted_val else "MISMATCH"
        comparison.append(
            {
                "assumption_id": assumption_id,
                "expected": expected_val,
                "predicted": predicted_val,
                "status": status,
            }
        )
    return comparison


def run_single_example(
    row: dict[str, str],
    shared_state: WorkflowState,
    graph: Runnable,
) -> EvalOutcome:
    user_query = (row.get("user_query") or "").strip()
    if not user_query:
        raise ValueError("Missing user_query in ground truth row")

    state: WorkflowState = {
        "user_query": user_query,
        **shared_state,
    }
    result_state = graph.invoke(state)
    selected_assumptions = result_state["selected_assumptions"]

    expected = normalize_expected(row)
    predicted = normalize_predicted(selected_assumptions)
    comparison = compare_assumptions(expected, predicted)

    passed = all(item["status"] == "MATCH" for item in comparison)
    return {
        "passed": passed,
        "expected": expected,
        "predicted": predicted,
        "comparison": comparison,
        "selected_assumptions": selected_assumptions,
        "intent_card": result_state.get("intent_card"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate interpreter outputs against ground truth labels."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run only the first N examples",
    )
    parser.add_argument(
        "--index",
        type=int,
        default=None,
        help="Run only the example at 1-based index",
    )
    return parser.parse_args()


def pick_examples(
        rows: list[dict[str, str]],
        limit: int | None,
        index: int | None
) -> list[dict[str, str]]:
    if index is not None:
        if index < 1 or index > len(rows):
            raise ValueError(f"index must be between 1 and {len(rows)}")
        return [rows[index - 1]]
    if limit is not None:
        return rows[:limit]
    return rows


def run_interpreter_evaluation() -> None:
    args = parse_args()

    ground_truth_rows = load_ground_truth(GROUND_TRUTH_CSV)
    rows_to_run = pick_examples(ground_truth_rows, args.limit, args.index)

    settings = Settings()
    table_cards = load_table_cards(settings=settings)
    assumption_catalog = load_assumption_catalog(settings=settings)

    client = create_llm_client(settings=settings)
    interpreter_graph = build_interpreter_subgraph(client)

    shared_state: WorkflowState = {
        "table_cards": table_cards,
        "assumption_catalog": assumption_catalog,
    }

    total = len(rows_to_run)
    passed = 0

    for idx, row in enumerate(rows_to_run, start=1):
        outcome = run_single_example(row, shared_state, interpreter_graph)
        if outcome["passed"]:
            passed += 1

        print(f"\n[{idx}/{total}] Query: {row['user_query']}")
        for item in outcome["comparison"]:
            print(
                f"  - {item['assumption_id']}: expected={item['expected']} | "
                f"predicted={item['predicted']} | status={item['status']}"
            )
        print("  Selected assumptions:")
        for assumption in sorted(
            outcome["selected_assumptions"], key=lambda a: a.assumption_id
        ):
            print(
                f"    * {assumption.assumption_id}: {assumption.selected_value} "
                f"(rationale: {assumption.rationale})"
            )

    percent = (passed / total * 100) if total else 0.0
    print("\nSummary:")
    print(f"  Passed {passed}/{total} examples ({percent:.1f}%)")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    run_interpreter_evaluation()
