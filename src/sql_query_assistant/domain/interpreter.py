from pydantic import BaseModel, Field


class AvailableOption(BaseModel):
    """A catalog option annotated with whether it was selected."""

    value: str
    label: str | None = None
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
    available_options: list[AvailableOption] | None = Field(
        None, description="All available options with selected flag"
    )


class InterpreterResponse(BaseModel):
    """Interpreter selections enriched for downstream steps and user display."""

    assumption_choices: list[SelectedAssumption] = Field(..., description="Selected assumptions list")
