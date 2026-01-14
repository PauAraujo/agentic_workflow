"""
Table card domain models for representing database schema information.

Optimized structure with:
- Compact FK notation ("SCHEMA.TABLE.COLUMN") at column level
- Deduplicated value_maps at table level, referenced by columns via value_map_ref
"""
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class TableMetadata(BaseModel):
    """Metadata describing a database table."""

    model_config = ConfigDict(extra="allow")

    qualified_name: str = Field(description="Schema-qualified table name (e.g., 'ICSR.PATIENT')")
    schema_name: str = Field(description="Database schema name (e.g., 'ICSR', 'ICSR_LOOKUP')")
    name: str = Field(description="Table name without schema prefix")
    description: Optional[str] = None
    synonyms: list[str] = Field(default_factory=list)
    primary_key: list[str] = Field(default_factory=list)
    row_count: int | None = None


class Column(BaseModel):
    """Column definition with optional FK reference and value map."""

    model_config = ConfigDict(extra="allow")

    name: str
    type: str
    description: Optional[str] = None
    nullable: bool = True

    # Compact FK format: "SCHEMA.TABLE.COLUMN"
    fk: str | None = Field(
        default=None,
        description="Foreign key reference in format 'SCHEMA.TABLE.COLUMN'"
    )

    # Reference to deduplicated value_map at table level
    value_map_ref: str | None = Field(
        default=None,
        description="Key into TableCard.value_maps for this column's lookup values"
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
    """Structured representation of a table card JSON file."""

    model_config = ConfigDict(extra="allow")

    table_metadata: TableMetadata
    columns: list[Column] = Field(default_factory=list)
    special_handling: dict[str, str] | None = None

    # Deduplicated value_maps at table level
    # Each value_map contains:
    #   - "_count": int (total values in lookup table)
    #   - "_value_column": str (column name for text search, only for sampled maps)
    #   - key->value string mappings
    value_maps: dict[str, dict[str, str | int]] | None = Field(
        default=None,
        description="Lookup table value mappings with metadata, keyed by table name"
    )

    def get_value_map(self, column: Column) -> dict[str, str | int] | None:
        """
        Get the value map for a column (includes metadata fields).

        Args:
            column: Column to get value map for

        Returns:
            Value map dict (with _count, optionally _value_column) or None
        """
        if column.value_map_ref and self.value_maps:
            return self.value_maps.get(column.value_map_ref)
        return None

    def get_value_map_count(self, column: Column) -> int | None:
        """Get the total count of values in a lookup table."""
        vmap = self.get_value_map(column)
        if vmap:
            return vmap.get("_count")
        return None

    def get_value_map_search_column(self, column: Column) -> str | None:
        """Get the column name to use for text search in large lookup tables."""
        vmap = self.get_value_map(column)
        if vmap:
            return vmap.get("_value_column")
        return None
