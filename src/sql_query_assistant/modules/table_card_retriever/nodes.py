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
        logger.warning(
            "Azure AI Search not configured; falling back to loading all table cards"
        )
        all_cards = load_table_cards(settings)
        return {STATE_KEY_TABLE_CARDS: all_cards}

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
            logger.warning("No relevant table cards found; falling back to all tables")
            all_cards = load_table_cards(settings)
            return {STATE_KEY_TABLE_CARDS: all_cards}

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
        logger.warning("Falling back to loading all table cards")
        all_cards = load_table_cards(settings)
        return {STATE_KEY_TABLE_CARDS: all_cards}
