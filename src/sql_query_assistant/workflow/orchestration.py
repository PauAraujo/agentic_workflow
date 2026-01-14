import logging

from pathlib import Path

from ..config import Settings
from ..llm_client import create_llm_client
from ..state import WorkflowState
from ..utils import (
    load_assumption_catalog,
    load_table_cards,
    transform_table_card_types,
    get_available_schemas,
)
from .main_graph import build_main_graph


logger = logging.getLogger(__name__)


def run_workflow(
    user_query: str,
    settings: Settings,
    table_cards_path: Path | None = None,
    schemas: list[str] | None = None,
    assumptions_path: Path | None = None,
    enable_persistence: bool = True,
    use_rag: bool = True,
) -> WorkflowState:
    """
    Run the end-to-end workflow for a single query.

    Args:
        user_query: Natural language query to convert to SQL.
        settings: Settings instance for LLM + persistence.
        table_cards_path: Optional override for table cards directory.
        schemas: Optional list of schema names to load table cards from.
                 If None, loads from all schemas in table_cards_dir.
        assumptions_path: Optional override for assumptions catalog file.
        enable_persistence: Whether to run the persistence step.
        use_rag: Whether to use RAG-based table card retrieval via Azure Search.
                 If False or Azure Search not configured, loads all table cards upfront.
                 Defaults to True.

    Returns:
        Final workflow state containing intent card, SQL draft, and optional run_id.
    """
    # Validate schemas upfront if provided
    if schemas is not None:
        if len(schemas) == 0:
            raise ValueError(
                "schemas list cannot be empty. Use None to query all schemas or provide "
                "at least one schema name."
            )

        # Validate that specified schemas exist
        available_schemas = get_available_schemas(settings)
        invalid_schemas = [s for s in schemas if s not in available_schemas]
        if invalid_schemas:
            raise ValueError(
                f"Invalid schema(s): {invalid_schemas}. "
                f"Available schemas: {list(available_schemas.keys())}"
            )

        logger.info(f"Workflow restricted to schemas: {schemas}")
    else:
        logger.info("Workflow using all available schemas")

    # Always load assumption catalog
    logger.info("Loading assumption catalog...")
    assumption_catalog = load_assumption_catalog(
        settings=settings,
        catalog_path=assumptions_path,
    )

    # Decide whether to load table cards upfront or let RAG retriever handle it
    table_cards = []
    if use_rag and settings.azure_search:
        logger.info(
            "RAG mode enabled: table cards will be retrieved dynamically by "
            "the table_card_retriever node using Azure AI Search"
        )
    else:
        if use_rag and not settings.azure_search:
            logger.warning(
                "RAG mode requested but Azure Search not configured; "
                "falling back to loading all table cards"
            )
        else:
            logger.info("Loading all table cards from disk...")

        table_cards = load_table_cards(
            settings=settings,
            base_path=table_cards_path,
            schemas=schemas
        )

        # Transform table card types from Oracle to target dialect if needed
        if settings.target_sql_dialect.lower() == "sqlite":
            logger.info("Transforming table card types from Oracle to SQLite...")
            table_cards = transform_table_card_types(
                table_cards,
                source_dialect="oracle",
                target_dialect="sqlite",
            )
            logger.info("Table card types transformed to SQLite")

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
        "allowed_schemas": schemas,
    }

    logger.info("Processing query: %s", initial_state["user_query"])
    return main_graph.invoke(initial_state)
