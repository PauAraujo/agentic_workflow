import logging

from .models import TableSelectionResponse
from .prompts import SYSTEM_PROMPT, USER_PROMPT
from sql_query_assistant.llm_client import LLMClient
from sql_query_assistant.config import Settings, ModelConfig
from sql_query_assistant.prompting import prompt_factory
from sql_query_assistant.state import WorkflowState
from sql_query_assistant.domain import TableCard

logger = logging.getLogger(__name__)


def _format_table_card(
    table_card: TableCard,
    noise_value_maps: set[str],
    verbose: bool = True,
) -> str:
    """
    Format a table card as a text summary for the LLM prompt.

    Args:
        table_card: The table card to format.
        noise_value_maps: Set of value map names to exclude (uppercase).
        verbose: If True, use detailed format with columns section and longer labels.
                 If False, use compact format for "other available" tables.

    Returns:
        Formatted string representation of the table card.

    Example verbose output:
        Table: ICSR.PATIENT
          Description: Patient demographics information
          Row count: 32,266,983
          Columns:
            - SAFETY_REPORT_ID: Foreign key linking to the safety report
            - PATIENT_SEX_ID: Gender of the patient
          Foreign keys: PATIENT_SEX_ID -> ICSR_LOOKUP.PATIENT_SEX.PATIENT_SEX_ID
          Lookups: PATIENT_SEX (all 2 values): Male, Female

    Example compact output:
        ICSR.SAFETY_REPORT
          Desc: The identification information of the safety report
          Rows: 30,862,461
          FKs: COUNTRY_ID -> ICSR_LOOKUP.COUNTRY.COUNTRY_ID
          Lookups: COUNTRY(3 of 259 shown, JOIN on NAME)=[UK, Germany...]
    """
    metadata = table_card.table_metadata
    lines = []

    # Header and basic info
    if verbose:
        lines.append(f"Table: {metadata.qualified_name}")
        lines.append(f"  Description: {metadata.description or 'No description'}")
        lines.append(f"  Row count: {metadata.row_count or 'Unknown'}")
    else:
        lines.append(metadata.qualified_name)
        if metadata.description:
            lines.append(f"  Desc: {metadata.description[:100]}")
        if metadata.row_count:
            lines.append(f"  Rows: {metadata.row_count:,}")

    # Columns section (verbose only)
    if verbose:
        cols_with_desc = []
        cols_without_desc = []
        for col in table_card.columns:
            if col.description and col.description.strip():
                desc = col.description.strip()[:80]
                cols_with_desc.append(f"    - {col.name}: {desc}")
            else:
                cols_without_desc.append(col.name)

        if cols_with_desc or cols_without_desc:
            lines.append("  Columns:")
            lines.extend(cols_with_desc)
            if cols_without_desc:
                lines.append(f"    - {', '.join(cols_without_desc)} (no description)")

    # Foreign keys
    fk_columns = [f"{col.name} -> {col.fk}" for col in table_card.columns if col.fk]
    if fk_columns:
        label = "Foreign keys" if verbose else "FKs"
        lines.append(f"  {label}: {', '.join(fk_columns)}")

    # Value maps
    if table_card.value_maps:
        meaningful_maps = {
            name: vmap for name, vmap in table_card.value_maps.items()
            if name.upper() not in noise_value_maps
        }

        sample_limit = 5 if verbose else 3
        vmap_parts = []

        for map_name, vmap in meaningful_maps.items():
            count = vmap.get("_count", len(vmap) - 1)
            is_sampled = "_value_column" in vmap
            real_values = [str(v) for k, v in vmap.items() if not str(k).startswith("_")]
            sample_values = real_values[:sample_limit]

            if not sample_values:
                continue

            search_col = vmap.get("_value_column", "NAME")

            if verbose:
                if is_sampled:
                    vmap_parts.append(
                        f"{map_name} ({len(sample_values)} of {count} shown, JOIN on {search_col} to find others): {', '.join(sample_values)}..."
                    )
                else:
                    ellipsis = "..." if len(real_values) > sample_limit else ""
                    vmap_parts.append(f"{map_name} (all {count} values): {', '.join(sample_values)}{ellipsis}")
            else:
                if is_sampled:
                    vmap_parts.append(f"{map_name}({len(sample_values)} of {count} shown, JOIN on {search_col})=[{', '.join(sample_values)}...]")
                else:
                    vmap_parts.append(f"{map_name}(all {count})=[{', '.join(sample_values)}...]")

        if vmap_parts:
            lines.append(f"  Lookups: {'; '.join(vmap_parts)}")

    return "\n".join(lines)


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

    Safety fallbacks:
    - If LLM call fails → return original tables
    - If LLM returns empty → return original tables
    - If LLM returns < 2 tables when we had >= 2 → return original tables

    Args:
        state: Current workflow state containing:
            - user_query: Natural language question
            - table_cards: Tables from retriever (already FK-expanded)
            - all_table_cards: Full catalog (for looking up core tables to add)
        client: LLMClient instance for LLM calls
        model_config: Model configuration specifying provider, model, and temperature
        settings: Settings instance containing table selector configuration

    Returns:
        Partial state update containing refined table_cards.
    """
    user_query = state.get("user_query", "")
    retrieved_cards = state.get("table_cards", [])
    all_cards = state.get("all_table_cards", [])

    # Early exit conditions
    if not user_query:
        logger.warning("No user query provided; skipping table selection")
        return {"table_cards": retrieved_cards}

    if not retrieved_cards:
        logger.warning("No retrieved tables; skipping table selection")
        return {"table_cards": retrieved_cards}

    # FALLBACK: If all_table_cards wasn't populated by the retriever, we can't
    # suggest adding new tables - we can only filter the retrieved set.
    # This happens if: retriever bug, standalone testing, or workflow misconfiguration.
    if not all_cards:
        logger.warning(
            "all_table_cards missing from state - table selector will only filter, "
            "cannot suggest adding tables. Ensure retriever populates all_table_cards."
        )
        all_cards = retrieved_cards

    logger.info(
        "Table selection: analyzing %d retrieved tables for query: '%s'",
        len(retrieved_cards),
        user_query[:100]
    )

    retrieved_names = {card.table_metadata.qualified_name for card in retrieved_cards}

    # Build lookup for quick access by qualified name
    all_cards_by_name = {
        card.table_metadata.qualified_name: card
        for card in all_cards
    }

    # BUILD "OTHER AVAILABLE" TABLES LIST
    # Core tables act as a safety net for critical tables the retriever might miss.

    # Get configurable values from settings
    core_tables = set(settings.table_selector.core_tables)
    noise_value_maps = {name.upper() for name in settings.table_selector.noise_value_maps}

    # Add core tables that aren't already in retrieved set
    other_available_tables = [
        all_cards_by_name[name]
        for name in core_tables
        if name in all_cards_by_name
        and name not in retrieved_names
    ]

    logger.info(
        "Other available tables: %d core tables (not already retrieved)",
        len(other_available_tables)
    )

    # Format prompt and call LLM
    # Retrieved tables get detailed summaries (more context for decision)
    retrieved_summaries = "\n\n".join(
        _format_table_card(card, noise_value_maps, verbose=True) for card in retrieved_cards
    )
    # Core tables (not already retrieved) get brief summaries as options to add
    other_summaries = "\n".join(
        _format_table_card(card, noise_value_maps, verbose=False) for card in other_available_tables
    )

    prompt_template = prompt_factory(SYSTEM_PROMPT, USER_PROMPT)
    prompt_messages = prompt_template.format_messages(
        user_query=user_query,
        retrieved_tables=retrieved_summaries,
        other_tables=other_summaries if other_summaries else "(none - all core tables already retrieved)",
    )

    # Call LLM with structured output
    try:
        llm_response = client.call_llm(
            messages=prompt_messages,
            schema=TableSelectionResponse,
            model_config=model_config,
        )
    except Exception as e:
        logger.error("Table selection LLM call failed: %s", e)
        logger.info("Falling back to retrieved tables without refinement")
        return {"table_cards": retrieved_cards}

    # Process LLM response to build refined table set
    refined_cards: list[TableCard] = []
    kept_names: set[str] = set()

    # Process tables_to_keep (from retrieved set)
    for selected_table in llm_response.tables_to_keep:
        card = all_cards_by_name.get(selected_table.qualified_name)
        if card:
            refined_cards.append(card)
            kept_names.add(selected_table.qualified_name)
            logger.debug(
                "Keeping table %s: %s",
                selected_table.qualified_name,
                selected_table.reason
            )
        else:
            # LLM hallucinated a table name - log warning but continue
            logger.warning(
                "Table selector referenced unknown table: %s",
                selected_table.qualified_name
            )

    # Process tables_to_add (from other available set)
    added_count = 0
    for table_name in llm_response.tables_to_add:
        if table_name in kept_names:
            continue  # Already in the kept set, skip duplicate
        card = all_cards_by_name.get(table_name)
        if card:
            refined_cards.append(card)
            kept_names.add(table_name)
            added_count += 1
            logger.debug("Adding table: %s", table_name)
        else:
            logger.warning(
                "Table selector requested unknown table: %s",
                table_name
            )

    logger.info(
        "Table selection complete: %d retrieved -> %d kept + %d added = %d total",
        len(retrieved_cards),
        len(llm_response.tables_to_keep),
        added_count,
        len(refined_cards)
    )
    logger.info("Rationale: %s", llm_response.rationale)

    # Safety fallbacks: The LLM might make mistakes. These guards prevent catastrophic failures.
    # Guard 1: Never return empty result
    if not refined_cards:
        logger.warning(
            "Table selector returned empty result; keeping original %d tables",
            len(retrieved_cards)
        )
        return {"table_cards": retrieved_cards}

    # Guard 2: Don't reduce too aggressively (might drop needed tables)
    if len(refined_cards) < 2 and len(retrieved_cards) >= 2:
        logger.warning(
            "Table selector returned too few tables (%d); keeping original set",
            len(refined_cards)
        )
        return {"table_cards": retrieved_cards}

    return {"table_cards": refined_cards}
