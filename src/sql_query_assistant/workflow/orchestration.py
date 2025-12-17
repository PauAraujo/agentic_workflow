import logging

from pathlib import Path

from ..config import Settings
from ..llm_client import create_llm_client
from ..state import WorkflowState
from ..utils import load_assumption_catalog, load_table_cards
from .main_graph import build_main_graph


logger = logging.getLogger(__name__)


def run_workflow(
    user_query: str,
    settings: Settings,
    table_cards_path: Path | None = None,
    assumptions_path: Path | None = None,
    enable_persistence: bool = True,
) -> WorkflowState:
    """
    Run the end-to-end workflow for a single query.

    Args:
        user_query: Natural language query to convert to SQL.
        settings: Settings instance for LLM + persistence.
        table_cards_path: Optional override for table cards directory.
        assumptions_path: Optional override for assumptions catalog file.
        enable_persistence: Whether to run the persistence step.

    Returns:
        Final workflow state containing intent card, SQL draft, and optional run_id.
    """
    logger.info("Loading table cards and assumption catalog...")
    table_cards = load_table_cards(settings=settings, base_path=table_cards_path)
    assumption_catalog = load_assumption_catalog(
        settings=settings,
        catalog_path=assumptions_path,
    )

    llm_client = create_llm_client(settings=settings)

    logger.info("Building workflow graph...")
    main_graph = build_main_graph(
        llm_client,
        settings,
        enable_persistence=enable_persistence,
    )

    initial_state: WorkflowState = {
        "user_query": user_query,
        "table_cards": table_cards,
        "assumption_catalog": assumption_catalog,
    }

    logger.info("Processing query: %s", initial_state["user_query"])
    return main_graph.invoke(initial_state)
