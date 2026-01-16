from pydantic import BaseModel, Field


class SelectedTable(BaseModel):
    """
    A table selected by the LLM as relevant to the query.
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
        description="Columns from this table relevant to the query"
    )


class TableSelectionResponse(BaseModel):
    """
    Complete response from the table selection LLM call.
    """

    tables_to_keep: list[SelectedTable] = Field(
        ...,
        description="Tables from retrieved set that are needed"
    )
    tables_to_add: list[str] = Field(
        default_factory=list,
        description="Qualified names of additional tables to add from core tables"
    )
    rationale: str = Field(
        ...,
        description="Brief explanation of the table selection decision"
    )
