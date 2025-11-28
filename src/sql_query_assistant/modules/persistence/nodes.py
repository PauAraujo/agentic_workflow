import logging

from sql_query_assistant.config import Settings
from sql_query_assistant.state import WorkflowState

from .service import save_full_state_json, save_workflow_results

logger = logging.getLogger(__name__)


def persist_results(state: WorkflowState, settings: Settings) -> WorkflowState:
    """
    Persist workflow outputs and return the assigned run_id.

    Args:
        state: Current workflow state containing results to persist.
        settings: Settings instance providing output paths and other config.

    Returns:
        Updated workflow state with run_id of persisted results.
    """
    logger.info("Persisting workflow results")
    run_id = save_workflow_results(state, settings)
    save_full_state_json(state, settings, run_id)
    return {"run_id": run_id}
