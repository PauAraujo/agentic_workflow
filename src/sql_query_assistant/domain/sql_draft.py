from pydantic import BaseModel, Field


class SQLDraft(BaseModel):
    """
    SQL statement produced by the LLM (drafter or repairer).

    Used as both the LLM response schema and the workflow state model.
    """

    rationale: str = Field(..., description="Explanation of the SQL logic or what was fixed")
    sql: str = Field(..., description="SQL statement")
