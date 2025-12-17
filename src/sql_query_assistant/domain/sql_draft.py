from pydantic import BaseModel, Field


class SQLDraft(BaseModel):
    """Draft SQL statement produced by the sql_drafter agent."""

    sql: str = Field(..., description="Draft SQL statement addressing the task and assumptions")
    rationale: str = Field(
        ...,
        description="Short explanation of how the SQL satisfies the request",
    )
    tables_used: list[str] = Field(
        ...,
        description="Tables referenced in the draft query, if detected",
    )
    dialect: str = Field(
        ...,
        description="SQL dialect used for this query (e.g., 'sqlite', 'oracle', 'postgres')"
    )
