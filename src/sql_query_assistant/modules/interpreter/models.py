from pydantic import BaseModel, Field


class RawAssumptionSelection(BaseModel):
    """
    A single assumption selection as returned by the LLM.

    This is the minimal structure the LLM provides - just the assumption ID,
    the value it chose, and why it made that choice. It does NOT include any
    metadata from the catalog (labels, descriptions, etc.) - that gets added
    during enrichment.
    """

    id: str = Field(..., description="Assumption id from the catalog")
    option_value: str = Field(..., description="Chosen value for this assumption")
    rationale: str = Field(..., description="Short natural language justification")


class RawInterpreterResponse(BaseModel):
    """
    Complete LLM response containing all assumption selections.
    This is a wrapper around the list of selections, before enriching
    with catalog metadata.
    """

    assumptions: list[RawAssumptionSelection] = Field(
        ...,
        description="Selected assumptions list",
    )
