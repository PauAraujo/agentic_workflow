import json
import logging

from .models import RawSQLDraftResponse
from .prompts import SYSTEM_PROMPT, USER_PROMPT
from sql_query_assistant.llm_client import LLMClient
from sql_query_assistant.config import ModelConfig
from sql_query_assistant.prompting import prompt_factory
from sql_query_assistant.state import WorkflowState
from sql_query_assistant.domain import SQLDraft

logger = logging.getLogger(__name__)


def draft_sql(
    state: WorkflowState,
    client: LLMClient,
    model_config: ModelConfig,
    target_dialect: str,
) -> WorkflowState:
    """
    Draft a SQL query using the user query and available table metadata.

    Args:
        state: Current state containing user_query and table_cards.
        client: LLMClient instance for LLM calls.
        model_config: Model configuration specifying provider, model, and temperature.
        target_dialect: Target SQL dialect for query generation (e.g., 'sqlite', 'postgres').

    Returns:
        Partial state update containing the SQLDraft.
    """
    logger.info("Drafting SQL query (target dialect: %s)", target_dialect)
    prompt_template = prompt_factory(SYSTEM_PROMPT, USER_PROMPT)

    prompt_messages = prompt_template.format_messages(
        target_dialect=target_dialect,
        user_query=state["user_query"],
        table_cards=json.dumps(
            [card.model_dump() for card in state["table_cards"]],
            indent=2,
        ),
    )

    llm_response = client.call_llm(
        messages=prompt_messages,
        schema=RawSQLDraftResponse,
        model_config=model_config,
    )

    sql_draft = SQLDraft(
        sql=llm_response.sql,
        rationale=llm_response.rationale,
        tables_used=llm_response.tables_used,
        dialect=target_dialect,
    )
    logger.info("SQL draft generated (dialect: %s)", target_dialect)

    return {"sql_draft": sql_draft}
