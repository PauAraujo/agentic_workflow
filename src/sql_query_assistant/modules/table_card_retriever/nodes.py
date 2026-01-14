import re
import logging

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import (
    QueryType,
    QueryCaptionType,
    QueryAnswerType,
    VectorizedQuery,
)
from openai import AzureOpenAI

from sql_query_assistant.config import Settings
from sql_query_assistant.state import WorkflowState
from sql_query_assistant.domain import TableCard
from sql_query_assistant.utils.loaders import load_table_cards
from .models import TableCardSearchResult

logger = logging.getLogger(__name__)

# State keys
STATE_KEY_USER_QUERY = "user_query"
STATE_KEY_TABLE_CARDS = "table_cards"
STATE_KEY_ALLOWED_SCHEMAS = "allowed_schemas"

# Azure Search field names
FIELD_ID = "id"
FIELD_SCHEMA_NAME = "schema_name"
FIELD_TABLE_NAME = "table_name"
FIELD_QUALIFIED_NAME = "qualified_name"
FIELD_CONTENT_VECTOR = "content_vector"
FIELD_SEARCH_SCORE = "@search.score"
FIELD_RERANKER_SCORE = "@search.reranker_score"

# Azure Search configuration
SEMANTIC_CONFIG_NAME = "table-cards-semantic-config"
DEFAULT_FALLBACK_TOP_K = 5

# Embedding client cache (module-level singleton)
_embedding_client: AzureOpenAI | None = None


def _get_embedding_client(settings: Settings) -> AzureOpenAI:
    """Get or create a cached Azure OpenAI client for embeddings."""
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = AzureOpenAI(
            api_key=settings.azure.api_key,
            api_version=settings.azure.api_version,
            azure_endpoint=str(settings.azure.openai_endpoint)
        )
    return _embedding_client


def _generate_query_embedding(query: str, settings: Settings) -> list[float]:
    """
    Generate embedding vector for a search query.

    Args:
        query: User search query
        settings: Application settings with Azure OpenAI configuration

    Returns:
        Embedding vector as list of floats
    """
    client = _get_embedding_client(settings)
    deployment = settings.azure_search.embedding_deployment

    response = client.embeddings.create(
        input=[query],
        model=deployment
    )

    return response.data[0].embedding


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _score_card(card: TableCard, query_tokens: set[str], raw_query: str) -> tuple[int, float]:
    """
    Score a table card based on token overlap and exact name matches.

    Scoring weights:
    - Table name/synonym tokens: 5x weight (high priority)
    - Table description tokens: 2x weight (medium priority)
    - Column name tokens: 1x weight (standard priority)
    - Column description tokens: 0.5x weight (low priority)
    - Exact table name match: +10 bonus
    - Exact qualified name match: +15 bonus

    Returns:
        Tuple of (raw_score, normalized_score) where normalized_score is in [0, 1]
    """
    metadata = card.table_metadata

    # Score table name and synonyms (highest weight)
    table_name_parts = [metadata.name]
    table_name_parts.extend(metadata.synonyms or [])
    table_name_tokens = _tokenize(" ".join(table_name_parts))
    table_name_score = len(query_tokens.intersection(table_name_tokens)) * 5

    # Score table description (medium weight)
    table_desc_tokens = _tokenize(metadata.description or "")
    table_desc_score = len(query_tokens.intersection(table_desc_tokens)) * 2

    # Score column names (standard weight)
    column_name_parts = [col.name for col in card.columns]
    column_name_tokens = _tokenize(" ".join(column_name_parts))
    column_name_score = len(query_tokens.intersection(column_name_tokens)) * 1

    # Score column descriptions (lowest weight)
    column_desc_parts = [col.description for col in card.columns if col.description]
    column_desc_tokens = _tokenize(" ".join(column_desc_parts))
    column_desc_score = len(query_tokens.intersection(column_desc_tokens)) * 0.5

    # Sum weighted scores
    base_score = table_name_score + table_desc_score + column_name_score + column_desc_score

    # Bonus for exact name matches (increased from 3/5 to 10/15)
    bonus_score = 0
    if metadata.name.lower() in raw_query:
        bonus_score += 10
    if metadata.qualified_name.lower() in raw_query:
        bonus_score += 15

    raw_score = base_score + bonus_score

    # Normalize by query length to handle varying query sizes
    # Add 1 to avoid division by zero
    normalized_score = raw_score / (len(query_tokens) + 1) if query_tokens else 0.0

    return raw_score, normalized_score


def _select_fallback_table_cards(
    all_cards: list[TableCard],
    user_query: str,
    limit: int,
) -> list[TableCard]:
    """
    Select top-k table cards using token-based scoring.

    Args:
        all_cards: All available table cards
        user_query: User's search query
        limit: Maximum number of cards to return

    Returns:
        List of top-k scored table cards
    """
    query_tokens = _tokenize(user_query)
    if not query_tokens:
        logger.debug("No query tokens found; returning first tables")
        return all_cards[:limit]

    # Score all cards
    scored = [
        (card, *_score_card(card, query_tokens, user_query.lower()))
        for card in all_cards
    ]
    # Sort by raw score (desc), then by qualified name (asc) for stability
    scored.sort(
        key=lambda item: (-item[1], item[0].table_metadata.qualified_name)
    )

    # Log top scores for debugging
    logger.debug(f"Token-based scoring for query '{user_query}':")
    for i, (card, raw_score, norm_score) in enumerate(scored[:min(10, len(scored))], 1):
        logger.debug(
            f"  {i}. {card.table_metadata.qualified_name}: "
            f"score={raw_score:.1f}, normalized={norm_score:.3f}"
        )

    # Return cards with score > 0, or fallback to first cards if none match
    top_cards = [card for card, raw_score, _ in scored if raw_score > 0][:limit]
    if top_cards:
        return top_cards

    logger.debug("No cards with positive scores; returning first tables")
    return all_cards[:limit]


def _get_fallback_limit(settings: Settings) -> int:
    """Get consistent fallback limit across all fallback scenarios."""
    if settings.azure_search and settings.azure_search.core_count:
        return settings.azure_search.core_count
    return DEFAULT_FALLBACK_TOP_K


def _expand_with_fk_relationships(
    core_cards: list[TableCard],
    all_cards: list[TableCard],
    settings: Settings,
) -> list[TableCard]:
    """
    Expand core table cards by adding their FK relationship neighbors.

    For the top N core tables (based on settings), finds:
    - Forward FKs: tables that the core table references
    - Reverse FKs: tables that reference the core table (optional)

    Prioritizes ICSR_LOOKUP schema tables and deduplicates against core cards.

    Args:
        core_cards: List of core table cards (already selected/ranked)
        all_cards: All available table cards for FK lookup
        settings: Application settings with FK expansion configuration

    Returns:
        List of expanded table cards (core + FK neighbors), capped at max_total
    """
    if not settings.azure_search or not settings.azure_search.fk_expansion_enabled:
        return core_cards

    # Get expansion parameters
    source_count = settings.azure_search.fk_expansion_source_count
    max_total = settings.azure_search.fk_expansion_max_total
    include_reverse = settings.azure_search.fk_expansion_include_reverse

    if source_count == 0:
        return core_cards[:max_total]

    # Build lookup index: qualified_name -> TableCard
    all_cards_by_name = {
        card.table_metadata.qualified_name: card
        for card in all_cards
    }

    # Track expanded tables (using qualified names)
    core_qualified_names = {card.table_metadata.qualified_name for card in core_cards}
    expanded_qualified_names: set[str] = set()

    # Expand from top N source cards
    expansion_source_cards = core_cards[:source_count]
    logger.info(
        f"Expanding FK relationships from top {len(expansion_source_cards)} core tables: "
        f"{', '.join(c.table_metadata.qualified_name for c in expansion_source_cards)}"
    )

    for source_card in expansion_source_cards:
        # Forward FKs: tables this card references
        for col in source_card.columns:
            if col.fk_qualified_table:
                # Skip if already in core or already expanded
                if col.fk_qualified_table not in core_qualified_names:
                    expanded_qualified_names.add(col.fk_qualified_table)
                    logger.debug(
                        f"  Forward FK: {source_card.table_metadata.qualified_name}.{col.name} "
                        f"-> {col.fk_qualified_table}"
                    )

        # Reverse FKs: tables that reference this card (optional)
        if include_reverse:
            source_qualified_name = source_card.table_metadata.qualified_name
            for candidate_card in all_cards:
                # Skip if this is the source card itself or already in core
                candidate_qualified_name = candidate_card.table_metadata.qualified_name
                if candidate_qualified_name in core_qualified_names:
                    continue

                # Check if any column references the source card
                for col in candidate_card.columns:
                    if col.fk_qualified_table == source_qualified_name:
                        expanded_qualified_names.add(candidate_qualified_name)
                        logger.debug(
                            f"  Reverse FK: {candidate_qualified_name}.{col.name} "
                            f"-> {source_qualified_name}"
                        )
                        break  # Only need one FK reference to include this table

    # Prioritize ICSR_LOOKUP tables (lookup/reference tables are typically small and critical)
    lookup_tables = [
        name for name in expanded_qualified_names
        if name.startswith("ICSR_LOOKUP.")
    ]
    other_tables = [
        name for name in expanded_qualified_names
        if not name.startswith("ICSR_LOOKUP.")
    ]

    # Combine: core + lookup tables + other tables, capped at max_total
    prioritized_names = list(core_qualified_names) + sorted(lookup_tables) + sorted(other_tables)
    final_qualified_names = prioritized_names[:max_total]

    # Build final list preserving core card order, then expanded cards
    final_cards = []

    # Add core cards first (preserving their ranking order)
    for card in core_cards:
        if card.table_metadata.qualified_name in final_qualified_names:
            final_cards.append(card)

    # Add expanded cards (sorted for stability)
    expanded_cards = []
    for qualified_name in final_qualified_names:
        if qualified_name not in core_qualified_names:
            card = all_cards_by_name.get(qualified_name)
            if card:
                expanded_cards.append(card)
            else:
                logger.warning(
                    f"FK expansion found reference to {qualified_name} "
                    f"but no table card exists"
                )

    # Sort expanded cards: ICSR_LOOKUP first, then alphabetically
    expanded_cards.sort(
        key=lambda c: (
            0 if c.table_metadata.schema_name == "ICSR_LOOKUP" else 1,
            c.table_metadata.qualified_name
        )
    )
    final_cards.extend(expanded_cards)

    logger.info(
        f"FK expansion: {len(core_cards)} core -> {len(final_cards)} total "
        f"(+{len(expanded_cards)} expanded, {len(lookup_tables)} lookup tables)"
    )
    logger.debug(
        f"Final table list: {', '.join(c.table_metadata.qualified_name for c in final_cards)}"
    )

    return final_cards


def _fallback_to_token_based_retrieval(
    user_query: str,
    settings: Settings,
    allowed_schemas: list[str] | None = None,
    reason: str = "Azure Search unavailable",
) -> list[TableCard]:
    """
    Fallback retrieval using token-based scoring when Azure Search unavailable.

    Loads table cards (optionally filtered by schema) and scores them based on
    token overlap with query. Also applies FK expansion if enabled.

    Args:
        user_query: User's search query
        settings: Application settings
        allowed_schemas: Optional list of schema names to load.
                        If None, loads from all schemas.
        reason: Reason for fallback (for logging)

    Returns:
        List of top-k scored table cards (with FK expansion if enabled)
    """
    limit = _get_fallback_limit(settings)
    logger.info(f"{reason}; using token-based fallback (limit={limit})")

    all_cards = load_table_cards(settings, schemas=allowed_schemas)
    core_cards = _select_fallback_table_cards(all_cards, user_query, limit)

    # Apply FK expansion if enabled
    expanded_cards = _expand_with_fk_relationships(
        core_cards=core_cards,
        all_cards=all_cards,
        settings=settings
    )

    return expanded_cards


def retrieve_relevant_table_cards(
    state: WorkflowState,
    settings: Settings,
) -> WorkflowState:
    """
    Retrieve relevant table cards using Azure AI Search based on user query.

    If Azure Search is not configured, falls back to loading all table cards.

    Args:
        state: Current workflow state containing user_query and allowed_schemas
        settings: Application settings with Azure Search configuration

    Returns:
        Partial state update with filtered table_cards list
    """
    user_query = state.get(STATE_KEY_USER_QUERY, "")
    allowed_schemas = state.get(STATE_KEY_ALLOWED_SCHEMAS)

    if not user_query:
        logger.warning("No user query provided; cannot retrieve table cards")
        return {STATE_KEY_TABLE_CARDS: []}

    # Check if Azure Search is configured
    if not settings.azure_search:
        fallback_cards = _fallback_to_token_based_retrieval(
            user_query,
            settings,
            allowed_schemas=allowed_schemas,
            reason="Azure AI Search not configured"
        )
        return {STATE_KEY_TABLE_CARDS: fallback_cards}

    logger.info(f"Retrieving relevant table cards for query: '{user_query}'")

    # Initialize Azure Search client
    search_client = SearchClient(
        endpoint=str(settings.azure_search.endpoint),
        index_name=settings.azure_search.table_cards_index_name,
        credential=AzureKeyCredential(settings.azure_search.query_key)
    )

    # Build OData filter for schema filtering
    schema_filter = None
    if allowed_schemas:
        # Azure Search OData syntax: schema_name eq 'ICSR' or schema_name eq 'ICSR_LOOKUP'
        filter_parts = [f"schema_name eq '{schema}'" for schema in allowed_schemas]
        schema_filter = " or ".join(filter_parts)
        logger.info(f"Applying schema filter: {schema_filter}")

    try:
        # Build search parameters
        search_params = {
            "search_text": user_query,
            "query_type": QueryType.SEMANTIC, # portal default: QueryType.SIMPLE (BM25) --> to experiment with
            "semantic_configuration_name": SEMANTIC_CONFIG_NAME, # specific to semantic search (remove if not using semantic)
            "query_caption": QueryCaptionType.EXTRACTIVE, # specific to semantic search (remove if not using semantic)
            "query_answer": QueryAnswerType.EXTRACTIVE, # specific to semantic search (remove if not using semantic)
            "top": settings.azure_search.top_k,
            "select": [FIELD_ID, FIELD_SCHEMA_NAME, FIELD_TABLE_NAME, FIELD_QUALIFIED_NAME],
        }

        # Add schema filter if schemas are restricted
        if schema_filter:
            search_params["filter"] = schema_filter

        # Add vector query for hybrid search if enabled
        if settings.azure_search.hybrid_search_enabled:
            logger.info("Using hybrid search (BM25 + vector + semantic reranker)")
            query_embedding = _generate_query_embedding(user_query, settings)

            vector_query = VectorizedQuery(
                vector=query_embedding,
                k_nearest_neighbors=settings.azure_search.top_k,
                fields=FIELD_CONTENT_VECTOR
            )
            search_params["vector_queries"] = [vector_query]
        else:
            logger.info("Using lexical search with semantic reranker (hybrid disabled)")

        # Perform hybrid search: BM25 + vector (RRF fusion) + semantic reranker
        results = search_client.search(**search_params)

        # Extract search results
        search_results: list[TableCardSearchResult] = []
        for result in results:
            search_result = TableCardSearchResult(
                id=result[FIELD_ID],
                schema_name=result[FIELD_SCHEMA_NAME],
                table_name=result[FIELD_TABLE_NAME],
                qualified_name=result[FIELD_QUALIFIED_NAME],
                score=result.get(FIELD_SEARCH_SCORE, 0.0),
                reranker_score=result.get(FIELD_RERANKER_SCORE)
            )
            search_results.append(search_result)
            logger.debug(
                f"Found table: {search_result.qualified_name} "
                f"(score: {search_result.score:.4f}, "
                f"reranker: {search_result.reranker_score})"
            )

        if not search_results:
            fallback_cards = _fallback_to_token_based_retrieval(
                user_query,
                settings,
                allowed_schemas=allowed_schemas,
                reason="No relevant table cards found in Azure Search"
            )
            return {STATE_KEY_TABLE_CARDS: fallback_cards}

        logger.info(f"Retrieved {len(search_results)} relevant table cards from Azure Search")

        # Load the full table cards for the matching tables (filtered by schemas if specified)
        all_table_cards = load_table_cards(settings, schemas=allowed_schemas)

        # Create a mapping from qualified name to table card
        table_cards_by_qualified_name = {
            card.table_metadata.qualified_name: card
            for card in all_table_cards
        }

        # Filter to only the relevant table cards, preserving search ranking order
        relevant_table_cards: list[TableCard] = []
        for search_result in search_results:
            card = table_cards_by_qualified_name.get(search_result.qualified_name)
            if card:
                relevant_table_cards.append(card)
            else:
                logger.warning(
                    f"Table card {search_result.qualified_name} found in search "
                    f"but not in loaded table cards"
                )

        # Select core cards (top N based on reranker score)
        core_count = settings.azure_search.core_count
        core_cards = relevant_table_cards[:core_count]

        logger.info(
            f"Selected {len(core_cards)} core table cards: "
            f"{', '.join(card.table_metadata.qualified_name for card in core_cards)}"
        )

        # Expand with FK relationships
        expanded_cards = _expand_with_fk_relationships(
            core_cards=core_cards,
            all_cards=all_table_cards,
            settings=settings
        )

        return {STATE_KEY_TABLE_CARDS: expanded_cards}

    except Exception as e:
        logger.error(f"Error retrieving table cards from Azure Search: {e}", exc_info=True)
        fallback_cards = _fallback_to_token_based_retrieval(
            user_query,
            settings,
            allowed_schemas=allowed_schemas,
            reason="Azure Search error"
        )
        return {STATE_KEY_TABLE_CARDS: fallback_cards}
