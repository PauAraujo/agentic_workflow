import json
import logging

from .models import RawInterpreterResponse, RawAssumptionSelection
from .prompts import SYSTEM_PROMPT, USER_PROMPT
from sql_query_assistant.llm_client import OpenAILLMClient
from sql_query_assistant.prompting import prompt_factory
from sql_query_assistant.state import WorkflowState
from sql_query_assistant.domain import (
    AssumptionCatalogEntry,
    AssumptionOption,
    AvailableOption,
    IntentCard,
    InterpreterResponse,
    SelectedAssumption,
)

logger = logging.getLogger(__name__)


def _resolve_fallback_value(
    catalog_entry: AssumptionCatalogEntry
) -> str:
    """
    Determine which option value to use when LLM's selection is invalid.

    Args:
        catalog_entry: Catalog entry with options and optional default value

    Returns:
        The catalog default if valid, otherwise the first available option.
    """
    first_option = catalog_entry.options[0].value
    if catalog_entry.default:
        # Verify the default value actually exists in options
        if any(opt.value == catalog_entry.default for opt in catalog_entry.options):
            return catalog_entry.default
        else:
            logger.warning(
                "Catalog assumption '%s' has invalid default '%s' not found in options; using first option",
                catalog_entry.id,
                catalog_entry.default
            )
            return first_option
    else:
        # No default specified, use first option as fallback
        return first_option


def _mark_selected_option(
    options: list[AssumptionOption],
    selected_value: str
) -> list[AvailableOption]:
    """
    Add 'selected' flags to options indicating which is currently selected.

    Args:
        options: Assumption options from assumptions catalog
        selected_value: The option value to mark as selected

    Returns:
        List of AvailableOption with exactly one marked as selected
    """
    return [
        AvailableOption(
            value=opt.value,
            label=opt.label,
            description=opt.description,
            selected=opt.value == selected_value,
        )
        for opt in options
    ]


def _validate_and_enrich_assumption(
    selection: RawAssumptionSelection,
    catalog_entry: AssumptionCatalogEntry
) -> SelectedAssumption | None:
    """
    Validate LLM's assumption selection and enrich with catalog metadata.

    Validates the selection has valid options and a resolvable value. Invalid
    selections are skipped and logged. Valid selections are enriched with
    labels, descriptions, and available option flags.

    Args:
        selection: Raw assumption selection from LLM
        catalog_entry: Catalog entry with validation rules and metadata

    Returns:
        SelectedAssumption with full metadata, or None if validation fails
    """
    # Verify assumption has valid options
    if not catalog_entry.options:
        logger.warning(
            "Assumption '%s' has no options in catalog; skipping",
            catalog_entry.id
        )
        return None

    selected_value = selection.option_value

    # Try to match the LLM's selected value against catalog options
    matched_option = next(
        (opt for opt in catalog_entry.options if opt.value == selected_value),
        None
    )

    # Handle invalid option values with fallback logic
    if matched_option is None:
        fallback_value = _resolve_fallback_value(catalog_entry)

        logger.warning(
            "Invalid option '%s' for assumption '%s'; falling back to '%s'",
            selected_value,
            catalog_entry.id,
            fallback_value,
        )

        selected_value = fallback_value
        matched_option = next(
            (opt for opt in catalog_entry.options if opt.value == fallback_value),
            None
        )

    # Final safety check - ensure we have a valid matched_option
    if matched_option is None:
        logger.error(
            "Could not resolve valid option for assumption '%s' with value '%s'; skipping",
            catalog_entry.id,
            selected_value
        )
        return None

    # Build and return enriched assumption with validated data
    return SelectedAssumption(
        assumption_id=catalog_entry.id,
        assumption_label=catalog_entry.label,
        selected_value=selected_value,
        selected_label=matched_option.label,
        option_description=matched_option.description,
        rationale=selection.rationale,
        available_options=_mark_selected_option(catalog_entry.options, selected_value),
    )


def interpret_query(
    state: WorkflowState,
    client: OpenAILLMClient,
) -> WorkflowState:
    """
    Select and validate assumptions based on user query and available tables.

    Uses an LLM to analyze the user query, table cards, and assumption catalog
    to determine which assumptions are relevant.
    The LLM response is validated and enriched to ensure data integrity.

    Validation performed:
    - Skipping assumptions with unknown IDs not in the catalog
    - Skipping assumptions with empty or missing options (malformed catalog entries)
    - Falling back to catalog defaults when LLM returns invalid option values
    - Validating that catalog defaults exist in the options list
    - Enriching selections with full metadata (labels, descriptions, available options)

    All validation errors are logged with appropriate severity levels. Invalid
    assumptions are skipped rather than propagated to prevent downstream errors.

    Args:
        state: Current state containing user_query, table_cards, and assumption_catalog
        client: OpenAILLMClient instance for LLM calls

    Returns:
        Partial state update containing the validated and enriched selected_assumptions list.
        Only successfully validated assumptions are included in the result.
    """
    logger.info("Interpreting query")

    # Build and format LLM prompt
    prompt_template = prompt_factory(SYSTEM_PROMPT, USER_PROMPT)
    prompt_template_formatted = prompt_template.format_messages(
        user_query=state["user_query"],
        table_cards=json.dumps(
            [card.model_dump() for card in state["table_cards"]],
            indent=2,
        ),
        assumption_catalog=json.dumps(
            [entry.model_dump() for entry in state["assumption_catalog"]],
            indent=2,
        ),
    )

    # Call LLM to get assumption selections
    llm_response = client.call_llm(
        messages=prompt_template_formatted,
        schema=RawInterpreterResponse,
    )

    # Build catalog lookup for validation
    catalog_by_id = {entry.id: entry for entry in state["assumption_catalog"]}

    enriched_assumptions: list[SelectedAssumption] = []
    for selection in llm_response.assumptions:
        # Verify assumption ID exists in catalog
        catalog_entry = catalog_by_id.get(selection.id)
        if not catalog_entry:
            logger.warning(
                "Interpreter returned unknown assumption id '%s'; skipping",
                selection.id
            )
            continue

        # Validate and enrich this assumption
        enriched = _validate_and_enrich_assumption(selection, catalog_entry)
        if enriched:
            enriched_assumptions.append(enriched)

    logger.info("Interpreter selected %d assumptions", len(enriched_assumptions))
    return {"selected_assumptions": enriched_assumptions}


def build_intent_card(state: WorkflowState) -> WorkflowState:
    """
    Build the final intent card from selected assumptions.

    Args:
        state: Current state containing user_query and assumptions

    Returns:
        Partial state update containing the constructed intent_card.
    """
    intent_card = IntentCard(
        task=state["user_query"],
        assumption_response=InterpreterResponse(assumption_choices=state["selected_assumptions"]),
    )
    logger.info("Built intent card")
    return {"intent_card": intent_card}
