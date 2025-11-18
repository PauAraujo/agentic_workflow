from typing import TypedDict, List, Dict, Any

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
    table_cards: List[Dict[str, Any]]
    assumption_catalog: List[Dict[str, Any]]
    assumptions: List[Dict[str, Any]]
    intent_card: Dict[str, Any]