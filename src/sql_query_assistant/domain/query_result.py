from pydantic import BaseModel, Field


class QueryResult(BaseModel):
    """Result of executing a SQL query against the database."""

    success: bool = Field(..., description="Whether the query executed successfully")
    row_count: int = Field(..., description="Number of rows returned")
    column_names: list[str] = Field(default_factory=list, description="Column names in result set")
    rows: list[dict] = Field(default_factory=list, description="Query result rows as dictionaries")
    error_message: str | None = Field(None, description="Error message if execution failed")
    execution_time_ms: float | None = Field(None, description="Query execution time in milliseconds")