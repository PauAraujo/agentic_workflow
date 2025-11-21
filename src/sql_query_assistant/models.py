from typing import TypedDict, Any
from pydantic import BaseModel, Field

class Assumption(BaseModel):
    """A single assumption selected from the catalog with its chosen value."""
    id: str = Field(..., description="Assumption id from the catalog")
    option_value: str = Field(..., description="Chosen value for this assumption")
    rationale: str = Field(..., description="Short natural language justification")

class InterpretationResponse(BaseModel):
    """Response model containing LLM-selected assumptions."""
    assumptions: list[Assumption] = Field(..., description="Selected assumptions list")

class IntentCard(BaseModel):
    """Final intent card containing the task and selected assumptions."""
    task: str = Field(..., description="High-level task to perform")
    assumption_response: InterpretationResponse = Field(..., description="Assumptions selected for the task")

class InterpreterState(TypedDict, total=False):
    """
    State object that flows through the query interpretation workflow.
    """
    user_query: str
    table_cards: list[dict[str, Any]]
    assumption_catalog: list[dict[str, Any]]
    assumptions: list[Assumption]
    intent_card: IntentCard