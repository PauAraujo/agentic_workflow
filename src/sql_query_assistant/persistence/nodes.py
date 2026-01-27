import logging

from sql_query_assistant.config import Settings
from sql_query_assistant.state import WorkflowState
from sql_query_assistant.persistence.service import save_workflow_results

logger = logging.getLogger(__name__)


def persist_results(state: WorkflowState, settings: Settings) -> WorkflowState:
    """
    Persist workflow outputs and return the assigned run_id.

    Args:
        state: Current workflow state containing results to persist.
        settings: Settings instance providing output paths and other config.

    Returns:
        Partial state update with run_id if persistence succeeded, or empty dict if skipped.
    """
    logger.info("Persisting workflow results")

    sql_draft = state.get("sql_draft")
    if not sql_draft:
        logger.warning("Missing sql_draft for persistence. Skipping save.")
        return {} # no state update

    run_id = save_workflow_results(state, settings)
    return {"run_id": run_id}
