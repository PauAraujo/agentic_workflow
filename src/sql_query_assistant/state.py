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
    all_table_cards: list[TableCard]  # available table cards for table_selector

    # Table Selector output
    table_cards_with_selection: list[TableCardWithSelection]  # enriched
    selection_rationale: str  # LLM's explanation of overall table selection strategy

    # SQL Drafter output
    sql_draft: SQLDraft

    # SQL Validator output
    validation_result: ValidationResult
    validation_history: list[ValidationResult]

    # SQL Repairer tracking
    repair_attempts: int
    repair_history: list[SQLDraft]

    # SQL Executor output
    query_result: QueryResult

    # Persistence output
    run_id: str
