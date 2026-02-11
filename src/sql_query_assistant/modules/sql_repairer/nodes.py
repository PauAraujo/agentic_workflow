import json
import logging

from sql_query_assistant.state import WorkflowState
from sql_query_assistant.domain import SQLDraft
from sql_query_assistant.llm_client import LLMClient
from sql_query_assistant.config import ModelConfig
from sql_query_assistant.prompting import build_chat_prompt
from .prompts import SYSTEM_PROMPT, USER_PROMPT

logger = logging.getLogger(__name__)


def repair_sql(
    state: WorkflowState,
    client: LLMClient,
    model_config: ModelConfig,
    target_dialect: str,
    max_repair_attempts: int,
) -> dict:
    """
    Attempt to repair SQL that failed validation using LLM.

    Args:
        state: Current workflow state with validation_result and sql_draft
        client: LLMClient instance for making repair calls
        model_config: Model configuration specifying provider, model, and temperature
        target_dialect: Target SQL dialect for query generation (e.g., 'sqlite', 'postgres')
        max_repair_attempts: Maximum number of repair attempts allowed

    Returns:
        Partial state update with repaired sql_draft, incremented repair_attempts,
        and updated repair_history. On LLM failure, sql_draft is omitted (unchanged).
    """
    validation_result = state.get("validation_result")
    sql_draft = state.get("sql_draft")
    user_query = state.get("user_query")
    table_cards_with_selection = state.get("table_cards_with_selection", [])
    table_cards = [tc.table_card for tc in table_cards_with_selection]
    repair_attempts = state.get("repair_attempts", 0)
    repair_history = state.get("repair_history", [])

    if not validation_result or not sql_draft or not user_query:
        logger.error("Missing required state for repair: validation_result, sql_draft, or user_query")
        return {}

    repair_attempts += 1
    logger.info("SQL repair attempt %d/%d (target dialect: %s)", repair_attempts, max_repair_attempts, target_dialect)

    error_summary = validation_result.get_error_summary()
    logger.debug("Validation errors to fix: %s", error_summary)

    prompt_template = build_chat_prompt(SYSTEM_PROMPT, USER_PROMPT)

    prompt_messages = prompt_template.format_messages(
        target_dialect=target_dialect,
        failed_sql=sql_draft.sql,
        validation_errors=error_summary,
        user_query=user_query,
        table_cards=json.dumps([tc.model_dump() for tc in table_cards], indent=2),
    )

    try:
        repaired_draft = client.call_llm(
            messages=prompt_messages,
            schema=SQLDraft,
            model_config=model_config,
        )
        logger.info("SQL repair completed (dialect: %s). New SQL: %s", target_dialect, repaired_draft.sql[:100])

        # On first repair, preserve the original draft in history so it's not lost
        if not repair_history:
            repair_history.append(sql_draft) # original failed draft

        # Track repair history for audit trail
        repair_history.append(repaired_draft)

        return {
            "sql_draft": repaired_draft,
            "repair_attempts": repair_attempts,
            "repair_history": repair_history
        }

    except Exception as e:
        logger.exception("Unexpected error during SQL repair: %s", e)
        return {
            "repair_attempts": repair_attempts,
            "repair_history": repair_history  # preserve history even on failure
        }
