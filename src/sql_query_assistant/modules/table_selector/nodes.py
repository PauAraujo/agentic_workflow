import json
import logging

from langchain_core.prompts import ChatPromptTemplate

from .prompts import SYSTEM_PROMPT, USER_PROMPT
from sql_query_assistant.llm_client import LLMClient
from sql_query_assistant.config import Settings, ModelConfig
from sql_query_assistant.state import WorkflowState
from sql_query_assistant.domain import (
    TableCard,
    TableCardWithSelection,
    TableSelectionResponse,
)

logger = logging.getLogger(__name__)


def _format_table_card_for_selector(
    table_card: TableCard,
    noise_value_maps: set[str],
) -> str:
    """
    Format a table card as JSON for the table selector LLM.

    Serializes the table card excluding redundant fields (schema_name, name,
    synonyms, value_map_ref, special_handling) and filtering noise value maps.

    Args:
        table_card: The table card to format.
        noise_value_maps: Set of value map names to exclude (uppercase).

    Returns:
        JSON-formatted string representation of the table card.
    """
    data = table_card.model_dump(
        exclude={
            "table_metadata": {"schema_name", "name", "synonyms"},
            "columns": {"__all__": {"value_map_ref"}},
            "special_handling": True,
        }
    )

    if data.get("value_maps"):
        data["value_maps"] = {
            k: v
            for k, v in data["value_maps"].items()
            if k.upper() not in noise_value_maps
        }

    return json.dumps(data, indent=2)


def select_tables(
    state: WorkflowState,
    client: LLMClient,
    model_config: ModelConfig,
    settings: Settings,
) -> WorkflowState:
    """
    Perform table selection to refine which tables are needed for the query.

    This is the main entry point called by the workflow graph. It:
        1. Takes tables from retriever (already FK-expanded by retriever)
        2. Shows them to an LLM with the user query
        3. LLM decides which to KEEP or DROP
        4. LLM can ADD core tables (safety net) if retriever missed them
        5. Returns refined table list for the SQL drafter

    Args:
        state: Current workflow state containing:
            - user_query: Natural language question
            - table_cards: Tables from retriever (already FK-expanded)
            - all_table_cards: Full catalog (for looking up core tables to add)
        client: LLMClient instance for LLM calls
        model_config: Model configuration specifying provider, model, and temperature
        settings: Settings instance containing table selector configuration

    Returns:
        Partial state update containing table_cards_with_selection (list of TableCardWithSelection)
        and selection_rationale (str).

    Raises:
        ValueError: If user_query is missing, retriever returned no tables,
            all_table_cards is missing from state, or LLM returns an empty selection.
    """
    user_query = state.get("user_query", "")
    retrieved_cards = state.get("table_cards", [])
    all_cards = state.get("all_table_cards", [])

    # Preconditions, fail fast on invalid input
    if not user_query:
        raise ValueError("No user query provided to table selector")

    if not retrieved_cards:
        raise ValueError(
            f"Retriever returned no tables for query: '{user_query[:100]}'"
        )

    if not all_cards:
        raise ValueError(
            "all_table_cards missing from state, retriever must populate this field"
        )

    logger.info(
        "Table selection: analyzing %d retrieved tables for query: '%s'",
        len(retrieved_cards),
        user_query[:100],
    )

    retrieved_names = {card.table_metadata.qualified_name for card in retrieved_cards}

    # Build lookup for quick access by qualified name
    all_cards_by_name = {card.table_metadata.qualified_name: card for card in all_cards}

    # BUILD "OTHER AVAILABLE" TABLES LIST
    # Core tables act as a safety net for critical tables the retriever might miss.

    # Get configurable values from settings
    core_tables = set(settings.table_selection.core_tables)
    noise_value_maps = {
        name.upper() for name in settings.table_selection.noise_value_maps
    }

    # Add core tables that aren't already in retrieved set
    other_available_tables = [
        all_cards_by_name[name]
        for name in core_tables
        if name in all_cards_by_name and name not in retrieved_names
    ]

    logger.info(
        "Other available tables: %d core tables (not already retrieved)",
        len(other_available_tables),
    )

    # Format prompt and call LLM
    # All tables get detailed summaries for informed decision-making
    retrieved_summaries = "\n\n".join(
        _format_table_card_for_selector(card, noise_value_maps)
        for card in retrieved_cards
    )
    # Core tables also get detailed summaries
    other_summaries = "\n\n".join(
        _format_table_card_for_selector(card, noise_value_maps)
        for card in other_available_tables
    )

    prompt_template = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", USER_PROMPT),
    ])
    prompt_messages = prompt_template.format_messages(
        user_query=user_query,
        retrieved_tables=retrieved_summaries,
        other_tables=other_summaries if other_summaries else "(none)",
    )

    # Call LLM with structured output (let exceptions propagate)
    llm_response = client.call_llm(
        messages=prompt_messages,
        schema=TableSelectionResponse,
        model_config=model_config,
    )

    # Process LLM response to build refined table set
    selected_cards: list[TableCardWithSelection] = []
    selected_names: set[str] = set()

    for table_selection in llm_response.selected_tables:
        # Skip duplicates
        if table_selection.qualified_name in selected_names:
            logger.warning(
                "Duplicate table in selection: %s (skipping)",
                table_selection.qualified_name,
            )
            continue

        # Look up the full table card
        card = all_cards_by_name.get(table_selection.qualified_name)
        if card:
            selected_cards.append(
                TableCardWithSelection(
                    table_card=card,
                    selection_reason=table_selection.selection_reason,
                    key_columns=table_selection.key_columns,
                )
            )
            selected_names.add(table_selection.qualified_name)
            logger.debug(
                "Selected table %s: %s",
                table_selection.qualified_name,
                table_selection.selection_reason,
            )
        else:
            # LLM hallucinated a table name, log warning but continue
            logger.warning(
                "Table selector referenced unknown table: %s",
                table_selection.qualified_name,
            )

    logger.info(
        "Table selection complete: %d retrieved + %d core available -> %d selected",
        len(retrieved_cards),
        len(other_available_tables),
        len(selected_cards),
    )
    logger.info("Selection rationale: %s", llm_response.rationale)

    # Validate LLM response, fail clearly rather than proceeding with bad data
    if not selected_cards:
        raise ValueError(
            f"Table selector returned empty result for query: '{user_query[:100]}'"
        )

    return {
        "table_cards_with_selection": selected_cards,
        "selection_rationale": llm_response.rationale,
    }
