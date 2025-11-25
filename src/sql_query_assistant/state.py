from typing import TypedDict

from sql_query_assistant.domain import (
    AssumptionCatalogEntry,
    IntentCard,
    SelectedAssumption,
    TableCard,
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

    # SQL Generator Output (future)
    # generated_sql: str
