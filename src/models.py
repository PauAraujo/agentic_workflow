from typing import TypedDict, Any

class AssumptionState(TypedDict, total=False):
    """
    State object that flows through the assumption selection workflow.

    Attributes:
        user_query: The user's natural language query
        table_cards: List of table metadata dictionaries
        assumption_catalog: List of assumption catalog entries
        assumptions: Selected assumptions with their chosen values
        intent_card: Final output containing task and assumptions
    """
    user_query: str
    table_cards: list[dict[str, Any]]
    assumption_catalog: list[dict[str, Any]]
    assumptions: list[dict[str, Any]]
    intent_card: dict[str, Any]