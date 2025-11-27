from pydantic import BaseModel, Field


class RawSQLDraftResponse(BaseModel):
    """
    Structured SQL draft returned by the LLM before any downstream enrichment.
    """

    sql: str = Field(..., description="Draft SQL statement")
    rationale: str = Field(..., description="Short reasoning describing how the query meets the task")
    tables_used: list[str] = Field(..., description="Tables referenced in the draft query")
