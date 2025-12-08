import json
import logging

from .models import RawInterpreterResponse
from .prompts import SYSTEM_PROMPT, USER_PROMPT
from sql_query_assistant.llm_client import OpenAILLMClient
from sql_query_assistant.prompting import prompt_factory
from sql_query_assistant.state import WorkflowState
from sql_query_assistant.domain import (
    AvailableOption,
    IntentCard,
    InterpreterResponse,
    SelectedAssumption,
)

logger = logging.getLogger(__name__)


def interpret_query(
    state: WorkflowState,
    client: OpenAILLMClient,
) -> WorkflowState:
    """
    Select and validate assumptions based on user query and available tables.

    This function uses an LLM to analyze the user query, table cards, and assumption
    catalog to determine which assumptions are relevant and what values they should have.
    The LLM response is validated and enriched with catalog metadata to ensure data integrity.

    Validation includes:
    - Skipping assumptions with unknown IDs not in the catalog
    - Skipping assumptions with empty or missing options (malformed catalog entries)
    - Falling back to catalog defaults when LLM returns invalid option values
    - Validating that catalog defaults actually exist in the options list
    - Enriching selections with full metadata (labels, descriptions, available options)

    Args:
        state: Current state containing user_query, table_cards, and assumption_catalog
        client: OpenAILLMClient instance for LLM calls

    Returns:
        Partial state update containing the validated and enriched selected_assumptions list.
        Invalid or unresolvable assumptions are logged and skipped rather than propagated.
    """
    logger.info("Interpreting query")
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
    llm_response = client.call_llm(
        messages=prompt_template_formatted,
        schema=RawInterpreterResponse,
        deployment_name="gpt-4o-mini",
        temperature=0.0
    )
    catalog_by_id = {entry.id: entry for entry in state["assumption_catalog"]}

    enriched_assumptions: list[SelectedAssumption] = []
    for selection in llm_response.assumptions:
        # Verify assumption ID exists in catalog
        # LLMs can hallucinate non-existent assumption IDs
        catalog_entry = catalog_by_id.get(selection.id)
        if not catalog_entry:
            logger.warning("Interpreter returned unknown assumption id '%s'; skipping", selection.id)
            continue

        # Verify assumption has valid options
        # A catalog entry without options is malformed and cannot be processed
        options = catalog_entry.options
        if not options:
            logger.warning(
                "Assumption '%s' has no options in catalog; skipping",
                catalog_entry.id
            )
            continue

        # Try to match the LLM's selected value against catalog options
        matched_option = next((opt for opt in options if opt.value == selection.option_value), None)
        selected_value = selection.option_value

        # Handle invalid option values with fallback logic
        if matched_option is None:
            # LLM returned an option value that doesn't exist in the catalog
            # Use catalog default if available, otherwise use first option
            if catalog_entry.default:
                # Verify the default value actually exists in options
                if any(opt.value == catalog_entry.default for opt in options):
                    fallback_value = catalog_entry.default
                else:
                    # Catalog is malformed: default doesn't exist in options
                    logger.error(
                        "Catalog assumption '%s' has invalid default '%s' not found in options; using first option",
                        catalog_entry.id,
                        catalog_entry.default
                    )
                    fallback_value = options[0].value
            else:
                # No default specified, use first option as fallback
                fallback_value = options[0].value

            # Log the fallback only if we're actually changing the value
            if selected_value != fallback_value:
                logger.warning(
                    "Invalid option '%s' for assumption '%s'; falling back to '%s'",
                    selected_value,
                    catalog_entry.id,
                    fallback_value,
                )

            selected_value = fallback_value
            matched_option = next((opt for opt in options if opt.value == selected_value), None)

        # Final safety check - ensure we have a valid matched_option
        # This should never happen after the fixes above, but guards against edge cases
        if matched_option is None:
            logger.error(
                "Could not resolve valid option for assumption '%s' with value '%s'; skipping",
                catalog_entry.id,
                selected_value
            )
            continue

        # Build the list of available options with selection flags
        # Mark which option is currently selected for UI display
        available_options = [
            AvailableOption(
                value=opt.value,
                label=opt.label,
                description=opt.description,
                selected=opt.value == selected_value,
            )
            for opt in options
        ] or None

        # Create the enriched assumption with validated data
        enriched_assumptions.append(
            SelectedAssumption(
                assumption_id=catalog_entry.id,
                assumption_label=catalog_entry.label,
                selected_value=selected_value,
                selected_label=matched_option.label,
                option_description=matched_option.description,
                rationale=selection.rationale,
                available_options=available_options,
            )
        )

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
