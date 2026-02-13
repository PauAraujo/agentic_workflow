from typing import TypedDict

from sql_query_assistant.domain import (
    TableCard,
    TableCardWithSelection,
    SQLDraft,
    QueryResult,
    ValidationResult,
    RetrievalResult,
)


class WorkflowState(TypedDict, total=False):
    """
    Global state shared across the full text-to-SQL workflow.

    Input values (user_query, allowed_schemas) are provided by the caller. Each module
    writes its outputs into the same state as the pipeline progresses.
    """

    # Input
    user_query: str
    allowed_schemas: list[str] | None  # None = all schemas

    # Table card retriever output
    retrieval_result: RetrievalResult  # detailed retrieval pipeline results
    table_cards: list[TableCard]  # final tables from retriever (before table selection)
    all_table_cards: list[
        TableCard
    ]  # all available table cards (for table_selector to add missing tables)

    # Table Selector output
    table_cards_with_selection: list[
        TableCardWithSelection
    ]  # enriched with selection context
    selection_rationale: str  # LLM's explanation of overall table selection strategy

    # SQL Drafter output
    sql_draft: SQLDraft

    # SQL Validator output
    validation_result: ValidationResult
    validation_history: list[
        ValidationResult
    ]  # all validation results (for preserving intermediate errors)

    # SQL Repairer tracking
    repair_attempts: int
    repair_history: list[SQLDraft]  # populated only when repair occurs

    # SQL Executor output
    query_result: QueryResult

    # Persistence output
    run_id: str
