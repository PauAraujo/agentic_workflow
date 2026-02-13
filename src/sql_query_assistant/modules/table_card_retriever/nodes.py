import logging

from openai import AzureOpenAI
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import (
    QueryType,
    QueryCaptionType,
    QueryAnswerType,
    VectorizedQuery,
)

from sql_query_assistant.config import Settings
from sql_query_assistant.state import WorkflowState
from sql_query_assistant.domain import TableCard, RetrievalResult
from sql_query_assistant.database import validate_schema_name
from sql_query_assistant.utils.loaders import load_table_cards
from sql_query_assistant.utils.type_mapper import transform_column_types
from .models import TableCardSearchResult

logger = logging.getLogger(__name__)

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

# Schema prioritization: ICSR_LOOKUP contains small reference/lookup tables
# that are frequently needed for JOINs but rarely surface in semantic search
# Prioritizing them in FK expansion ensures these critical tables are included
PRIORITY_SCHEMA = "ICSR_LOOKUP"

# Embedding client cache (module-level singleton)
_embedding_client: AzureOpenAI | None = None


def _get_embedding_client(settings: Settings) -> AzureOpenAI:
    """Get or create a cached Azure OpenAI client for embeddings."""
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = AzureOpenAI(
            api_key=settings.azure.api_key,
            api_version=settings.azure.api_version,
            azure_endpoint=str(settings.azure.openai_endpoint),
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

    response = client.embeddings.create(input=[query], model=deployment)

    return response.data[0].embedding


def _expand_with_fk_relationships(
    reranked_top_cards: list[TableCard],
    all_cards: list[TableCard],
    settings: Settings,
) -> tuple[list[TableCard], list[str]]:
    """
    Expand reranked top cards by adding their FK relationship neighbors.

    For the top N tables from the reranked results finds related tables via FK relationships:
    - Forward FKs: tables that the source table references
    - Reverse FKs: tables that reference the source table (optional)

    Prioritizes PRIORITY_SCHEMA tables (see constant) and deduplicates against existing cards.

    Args:
        reranked_top_cards: Table cards selected after semantic reranking
        all_cards: All available table cards for FK lookup
        settings: Application settings with FK expansion configuration

    Returns:
        Tuple of:
        - List of expanded table cards (reranked + FK neighbors), capped at max_total
        - List of qualified names of tables added via FK expansion
    """
    if not settings.azure_search or not settings.azure_search.fk_expansion_enabled:
        return reranked_top_cards, []

    # Get expansion parameters
    source_count = settings.azure_search.fk_expansion_source_count
    max_total = settings.azure_search.fk_expansion_max_total
    include_reverse = settings.azure_search.fk_expansion_include_reverse

    if source_count == 0:
        return reranked_top_cards[:max_total], []

    # Build lookup index: qualified_name -> TableCard
    all_cards_by_name = {card.table_metadata.qualified_name: card for card in all_cards}

    # Track which table cards we already have (to avoid duplicates during FK expansion)
    already_included = {
        card.table_metadata.qualified_name for card in reranked_top_cards
    }
    fk_neighbor_names: set[str] = set()

    # Select top N reranked cards as sources for FK expansion
    expansion_source_cards = reranked_top_cards[:source_count]
    logger.info(
        f"Expanding FK relationships from top {len(expansion_source_cards)} reranked tables: "
        f"{', '.join(c.table_metadata.qualified_name for c in expansion_source_cards)}"
    )

    for source_card in expansion_source_cards:
        # Forward FKs: tables this card references
        for col in source_card.columns:
            if col.fk_qualified_table:
                # Skip if already in reranked set
                if col.fk_qualified_table not in already_included:
                    fk_neighbor_names.add(col.fk_qualified_table)
                    logger.debug(
                        f"  Forward FK: {source_card.table_metadata.qualified_name}.{col.name} "
                        f"-> {col.fk_qualified_table}"
                    )

        # Reverse FKs: tables that reference this card (optional)
        if include_reverse:
            source_qualified_name = source_card.table_metadata.qualified_name
            for candidate_card in all_cards:
                # Skip if already in reranked set
                candidate_qualified_name = candidate_card.table_metadata.qualified_name
                if candidate_qualified_name in already_included:
                    continue

                # Check if any column references the source card
                for col in candidate_card.columns:
                    if col.fk_qualified_table == source_qualified_name:
                        fk_neighbor_names.add(candidate_qualified_name)
                        logger.debug(
                            f"  Reverse FK: {candidate_qualified_name}.{col.name} "
                            f"-> {source_qualified_name}"
                        )
                        break  # Only need one FK reference to include this table

    # Separate FK neighbors by schema for prioritization
    lookup_table_names = [
        name for name in fk_neighbor_names if name.startswith(f"{PRIORITY_SCHEMA}.")
    ]
    other_table_names = [
        name for name in fk_neighbor_names if not name.startswith(f"{PRIORITY_SCHEMA}.")
    ]
    # Find NAMES first to ensure stable ordering
    # Priority order: reranked cards > lookup tables > other FK tables
    # This ensures semantically relevant tables come first, then critical lookup tables
    prioritized_names = (
        [card.table_metadata.qualified_name for card in reranked_top_cards]
        + sorted(lookup_table_names)
        + sorted(other_table_names)
    )
    final_qualified_names = prioritized_names[:max_total]

    # Find CARD OBJECTS second to build final list
    # We preserve reranked order, then FK-expanded cards
    final_cards = []

    # Add reranked CARDS first (preserving their semantic ranking order)
    # Note: max_total may be smaller than len(reranked_top_cards), excluding some
    for card in reranked_top_cards:
        if card.table_metadata.qualified_name in final_qualified_names:
            final_cards.append(card)

    # Add FK-expanded cards next (we sort it after for stability)
    fk_expanded_cards = []
    for qualified_name in final_qualified_names:
        # Skip already included cards, which are already in final_cards
        if qualified_name not in already_included:
            card = all_cards_by_name.get(qualified_name)
            if card:
                fk_expanded_cards.append(card)
            else:
                # This should not happen, but log a warning if it does
                logger.warning(
                    f"FK expansion found reference to {qualified_name} "
                    f"but no table card exists"
                )

    # Sort FK-expanded cards: priority schema first, then alphabetically
    fk_expanded_cards.sort(
        key=lambda card: (
            0 if card.table_metadata.schema_name == PRIORITY_SCHEMA else 1,
            card.table_metadata.qualified_name,
        )
    )
    final_cards.extend(fk_expanded_cards)

    logger.info(
        f"FK expansion: {len(reranked_top_cards)} reranked -> {len(final_cards)} total "
        f"(+{len(fk_expanded_cards)} via FK, {len(lookup_table_names)} lookup tables)"
    )
    logger.debug(
        f"Final table list: {', '.join(c.table_metadata.qualified_name for c in final_cards)}"
    )

    # Return both the final cards and the list of FK-expanded table names
    fk_expanded_names = [c.table_metadata.qualified_name for c in fk_expanded_cards]
    return final_cards, fk_expanded_names


def retrieve_relevant_table_cards(
    state: WorkflowState,
    settings: Settings,
) -> WorkflowState:
    """
    Retrieve relevant table cards using Azure AI Search based on user query.

    Args:
        state: Current workflow state containing user_query and allowed_schemas
        settings: Application settings with Azure Search configuration

    Returns:
        Partial state update with filtered table_cards list

    Raises:
        ValueError: If Azure Search is not configured
    """
    user_query = state.get("user_query", "")
    allowed_schemas = state.get("allowed_schemas")

    if not user_query:
        logger.warning("No user query provided; cannot retrieve table cards")
        return {"table_cards": []}

    if not settings.azure_search:
        raise ValueError(
            "Azure Search configuration required for table card retrieval. "
            "Set AZURE_SEARCH_* environment variables."
        )

    logger.info(f"Retrieving relevant table cards for query: '{user_query}'")

    # Initialize Azure Search client
    search_client = SearchClient(
        endpoint=str(settings.azure_search.endpoint),
        index_name=settings.azure_search.table_cards_index_name,
        credential=AzureKeyCredential(settings.azure_search.query_key),
    )

    # Build OData filter for schema filtering
    schema_filter = None
    if allowed_schemas:
        # Validate schema names before interpolating into OData filter string
        for schema in allowed_schemas:
            validate_schema_name(schema)
        # Azure Search OData syntax: schema_name eq 'ICSR' or schema_name eq 'ICSR_LOOKUP'
        filter_parts = [f"schema_name eq '{schema}'" for schema in allowed_schemas]
        schema_filter = " or ".join(filter_parts)
        logger.info(f"Applying schema filter: {schema_filter}")

    try:
        # Candidate retrieval via Azure Search with semantic reranking
        # Uses hybrid search (BM25 + vector) if enabled, otherwise lexical only
        search_params = {
            "search_text": user_query,
            "query_type": QueryType.SEMANTIC,
            "semantic_configuration_name": SEMANTIC_CONFIG_NAME,  # specific to semantic search
            "query_caption": QueryCaptionType.EXTRACTIVE,  # specific to semantic search
            "query_answer": QueryAnswerType.EXTRACTIVE,  # specific to semantic search
            "top": settings.azure_search.top_k,
            "select": [
                FIELD_ID,
                FIELD_SCHEMA_NAME,
                FIELD_TABLE_NAME,
                FIELD_QUALIFIED_NAME,
            ],
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
                fields=FIELD_CONTENT_VECTOR,
            )
            search_params["vector_queries"] = [vector_query]
        else:
            logger.info("Using lexical search with semantic reranker (hybrid disabled)")

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
                reranker_score=result.get(FIELD_RERANKER_SCORE),
            )
            search_results.append(search_result)
            logger.debug(
                f"Found table: {search_result.qualified_name} "
                f"(score: {search_result.score:.4f}, "
                f"reranker: {search_result.reranker_score})"
            )

        if not search_results:
            logger.error(
                "Azure Search returned zero results. "
                "Diagnostic context: "
                f"query='{user_query}', "
                f"filter={schema_filter or 'none'}, "
                f"top_k={settings.azure_search.top_k}, "
                f"hybrid_search={'enabled' if settings.azure_search.hybrid_search_enabled else 'disabled'}, "
                f"semantic_config='{SEMANTIC_CONFIG_NAME}'"
            )
            raise RuntimeError(
                f"No relevant tables found for query: '{user_query}'. "
                "This is unusual — Azure Search normally returns results for any query. "
                f"Possible causes: {'schema filter may be too restrictive (' + schema_filter + '), ' if schema_filter else ''}"
                "index may be empty or misconfigured, or embeddings may not be deployed."
            )

        logger.info(
            f"Retrieved {len(search_results)} relevant table cards from Azure Search"
        )

        # Track tables from initial search (for RetrievalResult)
        tables_from_search = [sr.qualified_name for sr in search_results]

        # Load all table cards (unfiltered) to enable cross-schema FK expansion
        # Search results are already schema-filtered by Azure Search above
        all_table_cards = load_table_cards(settings)
        if settings.target_sql_dialect.lower() == "sqlite":
            all_table_cards = transform_column_types(
                all_table_cards, "oracle", "sqlite"
            )

        # Create a mapping from qualified name to table card
        table_cards_by_qualified_name = {
            card.table_metadata.qualified_name: card for card in all_table_cards
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

        # Take top N from reranked results (Azure Search already did the reranking)
        reranker_top_k = settings.azure_search.reranker_top_k
        selected_cards = relevant_table_cards[:reranker_top_k]

        # Track tables after reranking (for RetrievalResult)
        tables_after_rerank = [
            card.table_metadata.qualified_name for card in selected_cards
        ]

        logger.info(
            f"Selected top {len(selected_cards)} table cards after semantic reranking: "
            f"{', '.join(tables_after_rerank)}"
        )

        # FK expansion: add related tables via foreign key relationships
        expanded_cards, tables_from_fk_expansion = _expand_with_fk_relationships(
            reranked_top_cards=selected_cards,
            all_cards=all_table_cards,
            settings=settings,
        )

        # Build final table list for RetrievalResult
        tables_final = [card.table_metadata.qualified_name for card in expanded_cards]

        # Create RetrievalResult with full pipeline visibility
        retrieval_result = RetrievalResult(
            tables_from_search=tables_from_search,
            tables_after_rerank=tables_after_rerank,
            tables_from_fk_expansion=tables_from_fk_expansion,
            tables_final=tables_final,
        )

        return {
            "retrieval_result": retrieval_result,
            "table_cards": expanded_cards,
            "all_table_cards": all_table_cards,
        }

    except Exception as e:
        logger.error(
            f"Error retrieving table cards from Azure Search: {e}", exc_info=True
        )
        raise
