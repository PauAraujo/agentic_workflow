from typing import TypedDict

from sql_query_assistant.domain import (
    TableCard,
    TableCardWithSelection,
    SQLDraft,
    QueryResult,
    ValidationResult,
)


class WorkflowState(TypedDict, total=False):
    """
    Global state shared across the full text-to-SQL workflow.

    Input values (user_query, table_cards) are provided by the caller. Each module
    writes its outputs into the same state as the pipeline progresses.
    """

    # Input
    user_query: str
    table_cards: list[TableCard]  # Tables from retriever (before table selection)
    all_table_cards: list[TableCard]  # All available table cards (for table_selector to add missing tables)
    allowed_schemas: list[str] | None  # None = all schemas, empty list not allowed

    # Table Selector output
    table_cards_with_selection: list[TableCardWithSelection]  # Tables enriched with selection context

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
