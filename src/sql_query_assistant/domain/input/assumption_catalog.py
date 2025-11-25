from pydantic import BaseModel, ConfigDict, Field


class AssumptionOption(BaseModel):
    """Single selectable option for an assumption catalog entry."""

    model_config = ConfigDict(extra="allow")

    value: str
    label: str | None = None
    description: str | None = None
    sql_pattern: str | None = None


class AssumptionCatalogEntry(BaseModel):
    """Catalog entry describing an assumption and its possible choices."""

    model_config = ConfigDict(extra="allow")

    id: str
    label: str
    trigger_keywords: list[str] = Field(default_factory=list)
    description: str
    options: list[AssumptionOption] = Field(default_factory=list)
    default: str | None = None
