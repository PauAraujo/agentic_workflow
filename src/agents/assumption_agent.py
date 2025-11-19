import json

from langchain_openai import AzureChatOpenAI
from langfuse.langchain import CallbackHandler

from ..llm import call_llm
from ..models import AssumptionState, AssumptionResponse, IntentCard
from ..prompts import prompt_factory
from ..prompts.assumption_agent import SYSTEM_PROMPT, USER_PROMPT

def select_assumptions(
    state: AssumptionState,
    llm: AzureChatOpenAI,
    langfuse_handler: CallbackHandler
) -> AssumptionState:
    """
    Select relevant assumptions based on user query and available tables.

    This function uses an LLM to analyze the user query, table cards, and assumption
    catalog to determine which assumptions are relevant and what values they should have.

    Args:
        state: Current state containing user_query, table_cards, and assumption_catalog
        llm: Language model instance to use for selection
        langfuse_handler: Langfuse callback handler for tracing

    Returns:
        Partial state update containing assumptions list
    """
    prompt_template = prompt_factory(SYSTEM_PROMPT, USER_PROMPT)

    prompt_template_formatted = prompt_template.format_messages(
        user_query=state["user_query"],
        table_cards=json.dumps(state["table_cards"], indent=2),
        assumption_catalog=json.dumps(state["assumption_catalog"], indent=2)
    )

    llm_response = call_llm(
        llm=llm,
        langfuse_handler=langfuse_handler,
        messages=prompt_template_formatted,
        schema=AssumptionResponse,
    )

    return {"assumptions": llm_response.assumptions}


def build_intent_card(state: AssumptionState) -> AssumptionState:
    """
    Build the final intent card from selected assumptions.

    Args:
        state: Current state containing user_query and assumptions

    Returns:
        Partial state update containing intent_card
    """
    intent_card = IntentCard(
        task=state["user_query"],
        assumption_response=AssumptionResponse(
            assumptions=state["assumptions"]
        ),
    )
    return {"intent_card": intent_card}