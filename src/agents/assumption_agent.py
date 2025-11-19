import json

from typing import Any
from langchain_openai import AzureChatOpenAI

from ..models import AssumptionState
from ..prompts import prompt_factory
from ..prompts.assumption_agent import SYSTEM_PROMPT, USER_PROMPT

def select_assumptions(
    state: AssumptionState,
    llm: AzureChatOpenAI,
    langfuse_handler
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
        Updated state with selected assumptions added
    """
    chat_prompt = prompt_factory(SYSTEM_PROMPT, USER_PROMPT)

    # Format prompt with state variables
    messages = chat_prompt.format_messages(
        user_query=state["user_query"],
        table_cards=json.dumps(state["table_cards"], indent=2),
        assumption_catalog=json.dumps(state["assumption_catalog"], indent=2)
    )

    # Invoke LLM with tracing --> put in separate function?
    structured_llm = llm.with_structured_output(method='json_mode')  # to do: specify Pydantic class schema
    structured_response = structured_llm.invoke(messages, config={"callbacks": [langfuse_handler]})

    # Update and return state
    new_state: AssumptionState = dict(state)
    new_state["assumptions"] = structured_response
    return new_state


def build_intent_card(state: AssumptionState) -> AssumptionState:
    """
    Build the final intent card from selected assumptions.

    Args:
        state: Current state containing user_query and assumptions

    Returns:
        Updated state with intent_card added
    """
    intent_card: dict[str, Any] = {
        "task": state["user_query"],
        "assumptions": state["assumptions"],
    }

    new_state: AssumptionState = dict(state)
    new_state["intent_card"] = intent_card
    return new_state