import json

from ..llm_client import OpenAILLMClient
from ..models import InterpreterState, InterpretationResponse, IntentCard
from ..prompts import prompt_factory
from ..prompts.interpreter_agent import SYSTEM_PROMPT, USER_PROMPT

def interpret_query(
    state: InterpreterState,
    client: OpenAILLMClient,
) -> InterpreterState:
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
    prompt_template = prompt_factory(SYSTEM_PROMPT, USER_PROMPT)

    prompt_template_formatted = prompt_template.format_messages(
        user_query=state["user_query"],
        table_cards=json.dumps(state["table_cards"], indent=2),
        assumption_catalog=json.dumps(state["assumption_catalog"], indent=2)
    )
    llm_response = client.call_llm(
        messages=prompt_template_formatted,
        schema=InterpretationResponse,
        deployment_name="gpt-4o-mini",
        temperature=0.0
    )
    return {"assumptions": llm_response.assumptions}


def build_intent_card(state: InterpreterState) -> InterpreterState:
    """
    Build the final intent card from selected assumptions.

    Args:
        state: Current state containing user_query and assumptions

    Returns:
        Partial state update containing the constructed intent_card.
    """
    intent_card = IntentCard(
        task=state["user_query"],
        assumption_response=InterpretationResponse(
            assumptions=state["assumptions"]
        ),
    )
    return {"intent_card": intent_card}