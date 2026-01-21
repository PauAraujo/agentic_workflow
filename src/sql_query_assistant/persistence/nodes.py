import logging

from .service import save_full_state_json, save_workflow_results
from ..state import WorkflowState
from ..config import Settings


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

    sql_draft = state.get("sql_draft")
    if not sql_draft:
        logger.warning("Missing sql_draft for persistence. Skipping save.")
        return {}

    run_id = save_workflow_results(state, settings)
    save_full_state_json(state, settings, run_id)
    logger.info("Results saved with run_id=%d", run_id)

    return {"run_id": run_id}
