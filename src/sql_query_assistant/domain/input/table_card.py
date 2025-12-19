from pydantic import BaseModel, ConfigDict, Field


class TableMetadata(BaseModel):
    """Metadata describing a database table."""

    model_config = ConfigDict(extra="allow")

    schema_name: str = Field(
        default="main",
        description="Database schema name (e.g., 'ICSR', 'ICSR_EMA', 'ICSR_LOOKUP')"
    )
    name: str
    synonyms: list[str] = Field(default_factory=list)
    description: str
    primary_key: list[str] = Field(default_factory=list)

    @property
    def qualified_name(self) -> str:
        """Returns schema-qualified table name (e.g., 'ICSR.PATIENT')."""
        return f"{self.schema_name}.{self.name}"


class Column(BaseModel):
    """Column definition, with optional coded value map."""

    model_config = ConfigDict(extra="allow")

    name: str
    type: str
    description: str
    value_map: dict[str, str] | None = None


class TableCard(BaseModel):
    """Structured representation of a table card JSON file."""

    model_config = ConfigDict(extra="allow")

    table_metadata: TableMetadata
    columns: list[Column] = Field(default_factory=list)
    special_handling: dict[str, str] | None = None
