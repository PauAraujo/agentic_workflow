from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

class ForeignKeyReference(BaseModel):
    """Reference information for a foreign key."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_name: str = Field(alias="schema")
    table: str
    columns: list[str]


class ForeignKey(BaseModel):
    """Foreign key definition linking columns to a referenced table."""

    model_config = ConfigDict(extra="allow")

    columns: list[str]
    references: ForeignKeyReference


class TableMetadata(BaseModel):
    """Metadata describing a database table."""

    model_config = ConfigDict(extra="allow")

    schema_name: str = Field(
        default="main",
        description="Database schema name (e.g., 'ICSR', 'ICSR_EMA', 'ICSR_LOOKUP')"
    )
    name: str
    synonyms: list[str] = Field(default_factory=list)
    description: Optional[str] = None
    primary_key: list[str] = Field(default_factory=list)
    foreign_keys: list[ForeignKey] = Field(default_factory=list)
    row_count: int | None = None

    @property
    def qualified_name(self) -> str:
        """Returns schema-qualified table name (e.g., 'ICSR.PATIENT')."""
        return f"{self.schema_name}.{self.name}"


class ColumnReference(BaseModel):
    """Reference information for a column that is a foreign key."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_name: str = Field(alias="schema")
    table: str
    column: str


class Column(BaseModel):
    """Column definition, with optional coded value map."""

    model_config = ConfigDict(extra="allow")

    name: str
    type: str
    description: Optional[str] = None
    nullable: bool = True
    value_map: dict[str, str] | None = None
    references: ColumnReference | None = None


class TableCard(BaseModel):
    """Structured representation of a table card JSON file."""

    model_config = ConfigDict(extra="allow")

    table_metadata: TableMetadata
    columns: list[Column] = Field(default_factory=list)
    special_handling: dict[str, str] | None = None
