import json
import logging

from .models import RawSQLDraftResponse
from .prompts import SYSTEM_PROMPT, USER_PROMPT
from sql_query_assistant.llm_client import OpenAILLMClient
from sql_query_assistant.prompting import prompt_factory
from sql_query_assistant.state import WorkflowState
from sql_query_assistant.domain import SQLDraft

logger = logging.getLogger(__name__)


def draft_sql(
    state: WorkflowState,
    client: OpenAILLMClient,
    settings,
) -> WorkflowState:
    """
    Draft a SQL query using the intent card and available table metadata.

    Args:
        state: Current state containing intent_card and table_cards.
        client: OpenAILLMClient instance for LLM calls.
        settings: Settings instance for target SQL dialect configuration.

    Returns:
        Partial state update containing the SQLDraft.
    """
    target_dialect = settings.target_sql_dialect
    logger.info("Drafting SQL query (target dialect: %s)", target_dialect)
    prompt_template = prompt_factory(SYSTEM_PROMPT, USER_PROMPT)

    prompt_messages = prompt_template.format_messages(
        target_dialect=target_dialect,
        intent_card=json.dumps(state["intent_card"].model_dump(), indent=2),
        table_cards=json.dumps(
            [card.model_dump() for card in state["table_cards"]],
            indent=2,
        ),
    )

    llm_response = client.call_llm(
        messages=prompt_messages,
        schema=RawSQLDraftResponse,
        deployment_name="gpt-4o-mini",
        temperature=0.0,
    )

    sql_draft = SQLDraft(
        sql=llm_response.sql,
        rationale=llm_response.rationale,
        tables_used=llm_response.tables_used,
        dialect=target_dialect,
    )
    logger.info("SQL draft generated (dialect: %s)", target_dialect)

    return {"sql_draft": sql_draft}
