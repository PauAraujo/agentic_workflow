from typing import TypedDict

from sql_query_assistant.domain import (
    TableCard,
    AssumptionCatalogEntry,
    SelectedAssumption,
    IntentCard,
    SQLDraft,
    QueryResult,
    ValidationResult,
)


class WorkflowState(TypedDict, total=False):
    """
    Global state shared across the full text-to-SQL workflow.

    Input values (user_query, table_cards, assumption_catalog) are provided by the
    caller. Each module writes its outputs into the same state as the pipeline
    progresses (e.g., selected_assumptions, intent_card, generated_sql).
    """

    # Input
    user_query: str
    table_cards: list[TableCard]
    assumption_catalog: list[AssumptionCatalogEntry]

    # Interpreter output
    selected_assumptions: list[SelectedAssumption]
    intent_card: IntentCard

    # SQL Drafter output
    sql_draft: SQLDraft

    # SQL Validator output
    validation_result: ValidationResult

    # SQL Repairer tracking
    repair_attempts: int
    repair_history: list[SQLDraft]  # all SQL drafts created during repair attempts

    # SQL Executor output
    query_result: QueryResult

    # Persistence output
    run_id: int
