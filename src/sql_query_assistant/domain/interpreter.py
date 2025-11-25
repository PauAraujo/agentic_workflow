from pydantic import BaseModel, Field


class RawAssumptionSelection(BaseModel):
    """Minimal selection shape returned by the LLM."""

    id: str = Field(..., description="Assumption id from the catalog")
    option_value: str = Field(..., description="Chosen value for this assumption")
    rationale: str = Field(..., description="Short natural language justification")


class RawInterpreterResponse(BaseModel):
    """LLM payload before enrichment."""

    assumptions: list[RawAssumptionSelection] = Field(..., description="Selected assumptions list")


class OptionChoice(BaseModel):
    """Available option for an assumption, annotated with selection flag."""

    option_value: str
    option_label: str | None = None
    description: str | None = None
    selected: bool = False


class SelectedAssumption(BaseModel):
    """Interpreter choice enriched with catalog metadata for user display."""

    assumption_id: str = Field(..., description="Assumption id from the catalog")
    assumption_label: str | None = Field(None, description="Human-friendly label from the catalog")
    selected_value: str = Field(..., description="Chosen option value")
    selected_label: str | None = Field(None, description="Label of the chosen option")
    option_description: str | None = Field(None, description="Description of the chosen option")
    rationale: str = Field(..., description="Short natural language justification")
    available_options: list[OptionChoice] | None = Field(
        None, description="All available options with selected flag"
    )


class InterpreterResponse(BaseModel):
    """Interpreter selections enriched for downstream steps and user display."""

    assumption_choices: list[SelectedAssumption] = Field(..., description="Selected assumptions list")
