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
    Select relevant assumptions based on user query and available tables.

    This function uses an LLM to analyze the user query, table cards, and assumption
    catalog to determine which assumptions are relevant and what values they should have.

    Args:
        state: Current state containing user_query, table_cards, and assumption_catalog
        client: OpenAILLMClient instance for LLM calls

    Returns:
        Partial state update containing the selected assumptions list.
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
        catalog_entry = catalog_by_id.get(selection.id)
        label = catalog_entry.label if catalog_entry else None
        options = catalog_entry.options if catalog_entry else []
        matched_option = next((opt for opt in options if opt.value == selection.option_value), None)

        available_options = [
            AvailableOption(
                value=opt.value,
                label=opt.label,
                description=opt.description,
                selected=opt.value == selection.option_value,
            )
            for opt in options
        ] or None

        enriched_assumptions.append(
            SelectedAssumption(
                assumption_id=selection.id,
                assumption_label=label,
                selected_value=selection.option_value,
                selected_label=matched_option.label if matched_option else None,
                option_description=matched_option.description if matched_option else None,
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
