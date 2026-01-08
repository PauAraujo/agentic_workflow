from pydantic import BaseModel, Field


class RawSQLRepairResponse(BaseModel):
    """
    Structured SQL repair response returned by the LLM.
    """

    sql: str = Field(..., description="Repaired SQL statement")
    rationale: str = Field(..., description="Explanation of what was fixed and why")
    tables_used: list[str] = Field(
        ...,
        description="Schema-qualified table names referenced in the repaired query (e.g., ['SCHEMA.TABLE'])"
    )
