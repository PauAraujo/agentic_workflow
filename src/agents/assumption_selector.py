import json

from typing import Dict, Any
from langchain_openai import AzureChatOpenAI

from ..models import AssumptionState

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
    user_query = state["user_query"]
    table_cards = state["table_cards"]
    catalog = state["assumption_catalog"]

    # Construct the prompt
    prompt = f"""
You are an Assumption Agent for a text-to-SQL system.

Your job:
1. Look at the user query.
2. Look at the available tables.
3. Look at the assumption catalog.
4. For each catalog entry that is relevant to this query, pick a value.
5. Return a JSON array. No explanation outside JSON.

Input:
- User query:
{user_query}

- Table cards (JSON):
{json.dumps(table_cards, indent=2)}

- Assumption catalog (JSON):
{json.dumps(catalog, indent=2)}

Output format, strictly JSON, no extra text:

[
  {{"id": "time_basis", "value": "first_received", "why": "Reason in one sentence"}},
  {{"id": "age_dimension", "value": "age_group", "why": "Reason in one sentence"}}
]

Only use assumption ids and values that exist in the catalog.
If a catalog entry is clearly irrelevant, you may omit it.
"""

    # Invoke LLM with tracing
    structured_llm = llm.with_structured_output(method='json_mode') # to do: specify Pydantic class schema
    structured_response = structured_llm.invoke(prompt, config={"callbacks": [langfuse_handler]})

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
    intent_card: Dict[str, Any] = {
        "task": state["user_query"],
        "assumptions": state["assumptions"],
    }

    new_state: AssumptionState = dict(state)
    new_state["intent_card"] = intent_card
    return new_state