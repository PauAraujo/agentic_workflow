from pydantic import BaseModel, ConfigDict, Field, model_validator


class TableMetadata(BaseModel):
    """Metadata describing a database table."""

    model_config = ConfigDict(extra="allow", frozen=True)

    qualified_name: str = Field(
        description="Schema-qualified table name (e.g., 'ICSR.PATIENT')"
    )
    schema_name: str = Field(
        description="Database schema name (e.g., 'ICSR', 'ICSR_LOOKUP')"
    )
    name: str = Field(description="Table name without schema prefix")
    description: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    primary_key: list[str] = Field(default_factory=list)
    row_count: int | None = None

    @model_validator(mode="after")
    def _check_qualified_name_consistency(self) -> "TableMetadata":
        expected = f"{self.schema_name}.{self.name}"
        if self.qualified_name != expected:
            raise ValueError(
                f"qualified_name '{self.qualified_name}' does not match "
                f"'{expected}' (from schema_name + name)"
            )
        return self


class Column(BaseModel):
    """Column definition with optional FK reference and value map."""

    model_config = ConfigDict(extra="allow", frozen=True)

    name: str
    type: str
    description: str | None = None
    nullable: bool = True

    # Compact FK format: "SCHEMA.TABLE.COLUMN"
    fk: str | None = Field(
        default=None,
        description="Foreign key reference in format 'SCHEMA.TABLE.COLUMN'",
    )

    # Reference to deduplicated value_map at table level
    value_map_ref: str | None = Field(
        default=None,
        description="Key into TableCard.value_maps for this column's lookup values",
    )

    def get_fk_parts(self) -> tuple[str, str, str] | None:
        """
        Parse the FK string into (schema, table, column) parts.

        Returns:
            Tuple of (schema_name, table_name, column_name) or None if no FK
        """
        if not self.fk:
            return None
        parts = self.fk.split(".")
        if len(parts) != 3:
            return None
        return parts[0], parts[1], parts[2]

    @property
    def fk_qualified_table(self) -> str | None:
        """Get the qualified table name from the FK (e.g., 'ICSR_LOOKUP.COUNTRY')."""
        parts = self.get_fk_parts()
        if parts:
            return f"{parts[0]}.{parts[1]}"
        return None


class TableCard(BaseModel):
    """
    Immutable table schema metadata loaded from JSON files.

    Represents the complete structure of a database table including columns,
    foreign keys, value maps, and metadata. This is the foundational input
    model that flows through the entire pipeline.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    table_metadata: TableMetadata
    columns: list[Column] = Field(default_factory=list)
    special_handling: dict[str, str] | None = None

    # Deduplicated value_maps at table level
    # The presence/absence of _value_column signals completeness:
    #   - _value_column ABSENT: all lookup values embedded (≤500 rows), use IDs directly
    #   - _value_column PRESENT: sampled (>500 rows), JOIN on that column if value not found
    # All maps include "_count" (total values in lookup table)
    value_maps: dict[str, dict[str, str | int]] | None = Field(
        default=None,
        description="Lookup table value mappings with metadata, keyed by table name",
    )


class TableCardWithSelection(BaseModel):
    """
    TableCard enriched with selection context from the Table Selector.

    The table_card contains immutable schema metadata (columns, FKs, descriptions).
    The selection metadata (reason, key_columns) captures the LLM's decision context.
    """

    table_card: TableCard = Field(
        ..., description="The full table card with schema metadata"
    )
    selection_reason: str = Field(
        ...,
        description="Why the Table Selector determined this table is needed for the query",
    )
    key_columns: list[str] = Field(
        default_factory=list, description="Columns identified as relevant to the query"
    )
