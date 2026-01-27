from pydantic import BaseModel, ConfigDict, Field


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
    selection_reason: str = Field(
        ...,
        description="Why this table is needed for the query"
    )
    key_columns: list[str] = Field(
        default_factory=list,
        description="Columns from this table relevant to the query (may be empty if used only for JOINs)"
    )


class TableSelectionResponse(BaseModel):
    """
    Complete response from table selection LLM call.
    """

    model_config = ConfigDict(frozen=True)

    selected_tables: list[TableSelectionDecision] = Field(
        default_factory=list,
        description="All tables selected as needed for the query"
    )
    rationale: str | None = Field(
        default=None,
        description="Brief explanation of the table selection strategy"
    )
