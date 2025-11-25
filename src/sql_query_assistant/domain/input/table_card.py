from pydantic import BaseModel, ConfigDict, Field


class TableMetadata(BaseModel):
    """Metadata describing a database table."""

    model_config = ConfigDict(extra="allow")

    name: str
    synonyms: list[str] = Field(default_factory=list)
    description: str
    primary_key: list[str] = Field(default_factory=list)


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
