import re
import logging

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import QueryType, QueryCaptionType, QueryAnswerType

from sql_query_assistant.config import Settings
from sql_query_assistant.state import WorkflowState
from sql_query_assistant.domain import TableCard
from sql_query_assistant.utils.loaders import load_table_cards
from .models import TableCardSearchResult

logger = logging.getLogger(__name__)

# State keys
STATE_KEY_USER_QUERY = "user_query"
STATE_KEY_TABLE_CARDS = "table_cards"

# Azure Search field names
FIELD_ID = "id"
FIELD_SCHEMA_NAME = "schema_name"
FIELD_TABLE_NAME = "table_name"
FIELD_QUALIFIED_NAME = "qualified_name"
FIELD_SEARCH_SCORE = "@search.score"
FIELD_RERANKER_SCORE = "@search.reranker_score"

# Azure Search configuration
SEMANTIC_CONFIG_NAME = "table-cards-semantic-config"
DEFAULT_FALLBACK_TOP_K = 5  # Increased from 1 to provide more context


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
    if settings.azure_search and settings.azure_search.top_k:
        return settings.azure_search.top_k
    return DEFAULT_FALLBACK_TOP_K


def _fallback_to_token_based_retrieval(
    user_query: str,
    settings: Settings,
    reason: str = "Azure Search unavailable",
) -> list[TableCard]:
    """
    Fallback retrieval using token-based scoring when Azure Search unavailable.

    Loads all table cards and scores them based on token overlap with query.

    Args:
        user_query: User's search query
        settings: Application settings
        reason: Reason for fallback (for logging)

    Returns:
        List of top-k scored table cards
    """
    limit = _get_fallback_limit(settings)
    logger.info(f"{reason}; using token-based fallback (limit={limit})")

    all_cards = load_table_cards(settings)
    return _select_fallback_table_cards(all_cards, user_query, limit)


def retrieve_relevant_table_cards(
    state: WorkflowState,
    settings: Settings,
) -> WorkflowState:
    """
    Retrieve relevant table cards using Azure AI Search based on user query.

    If Azure Search is not configured, falls back to loading all table cards.

    Args:
        state: Current workflow state containing user_query
        settings: Application settings with Azure Search configuration

    Returns:
        Partial state update with filtered table_cards list
    """
    user_query = state.get(STATE_KEY_USER_QUERY, "")

    if not user_query:
        logger.warning("No user query provided; cannot retrieve table cards")
        return {STATE_KEY_TABLE_CARDS: []}

    # Check if Azure Search is configured
    if not settings.azure_search:
        fallback_cards = _fallback_to_token_based_retrieval(
            user_query,
            settings,
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

    try:
        # Perform semantic search with reranking
        results = search_client.search(
            search_text=user_query,
            query_type=QueryType.SEMANTIC,
            semantic_configuration_name=SEMANTIC_CONFIG_NAME,
            query_caption=QueryCaptionType.EXTRACTIVE,
            query_answer=QueryAnswerType.EXTRACTIVE,
            top=settings.azure_search.top_k,
            select=[FIELD_ID, FIELD_SCHEMA_NAME, FIELD_TABLE_NAME, FIELD_QUALIFIED_NAME],
        )

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
                reason="No relevant table cards found in Azure Search"
            )
            return {STATE_KEY_TABLE_CARDS: fallback_cards}

        logger.info(f"Retrieved {len(search_results)} relevant table cards from Azure Search")

        # Load the full table cards for the matching tables
        all_table_cards = load_table_cards(settings)

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

        logger.info(
            f"Selected {len(relevant_table_cards)} relevant table cards: "
            f"{', '.join(card.table_metadata.qualified_name for card in relevant_table_cards)}"
        )

        return {STATE_KEY_TABLE_CARDS: relevant_table_cards}

    except Exception as e:
        logger.error(f"Error retrieving table cards from Azure Search: {e}", exc_info=True)
        fallback_cards = _fallback_to_token_based_retrieval(
            user_query,
            settings,
            reason="Azure Search error"
        )
        return {STATE_KEY_TABLE_CARDS: fallback_cards}
