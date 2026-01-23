from pydantic import BaseModel, Field


class TableSelectionDecision(BaseModel):
    """
    Represents the LLM's decision to select a table for the query.

    This is a lightweight record of which table was chosen and why.
    The full table schema (TableCard) is looked up separately.
    """

    qualified_name: str = Field(
        ...,
        description="Schema-qualified table name (e.g., 'ICSR.PATIENT')"
    )
    reason: str = Field(
        ...,
        description="Why this table is needed for the query"
    )
    key_columns: list[str] = Field(
        default_factory=list,
        description="Columns from this table relevant to the query (may be empty if used only for JOINs)"
    )


class TableSelectionResponse(BaseModel):
    """
    Complete response from the table selection LLM call.
    """

    selected_tables: list[TableSelectionDecision] = Field(
        ...,
        description="All tables selected as needed for the query"
    )
    rationale: str = Field(
        ...,
        description="Brief explanation of the table selection strategy"
    )
