from pydantic import BaseModel, Field


class SQLDraft(BaseModel):
    """Draft SQL statement produced by the sql_drafter agent."""

    sql: str = Field(..., description="Draft SQL statement addressing the task and assumptions")
    rationale: str | None = Field(
        None,
        description="Short explanation of how the SQL satisfies the request",
    )
    tables_used: list[str] | None = Field(
        None,
        description="Tables referenced in the draft query, if detected",
    )
