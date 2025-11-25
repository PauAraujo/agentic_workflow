from pydantic import BaseModel, Field

from sql_query_assistant.domain.interpreter import InterpreterResponse


class IntentCard(BaseModel):
    """Final intent card containing the task and selected assumptions."""

    task: str = Field(..., description="High-level task to perform")
    assumption_response: InterpreterResponse = Field(..., description="Assumptions selected for the task")
