import logging

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField,
    SearchFieldDataType,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
)

from sql_query_assistant.config import Settings
from sql_query_assistant.utils.loaders import load_table_cards

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def create_table_cards_index(
    endpoint: str,
    admin_key: str,
    index_name: str,
    delete_if_exists: bool = True
) -> None:
    """
    Create the table cards search index with appropriate schema.

    Args:
        endpoint: Azure AI Search endpoint URL
        admin_key: Admin key for creating/updating indexes
        index_name: Name of the index to create
        delete_if_exists: Whether to delete existing index before creating
    """
    index_client = SearchIndexClient(endpoint, AzureKeyCredential(admin_key))

    # Delete existing index if requested
    if delete_if_exists:
        try:
            logger.info(f"Checking if index '{index_name}' exists...")
            index_client.get_index(index_name)
            logger.info(f"Deleting existing index '{index_name}'...")
            index_client.delete_index(index_name)
            logger.info(f"Index '{index_name}' deleted successfully")
        except Exception as e:
            if "not found" in str(e).lower():
                logger.info(f"Index '{index_name}' does not exist, proceeding with creation")
            else:
                logger.warning(f"Error checking/deleting index: {e}")

    logger.info(f"Creating index '{index_name}'...")

    # Define the index schema
    fields = [
        SimpleField(
            name="id",
            type=SearchFieldDataType.String,
            key=True,
            filterable=True,
            sortable=True
        ),
        SearchableField(
            name="schema_name",
            type=SearchFieldDataType.String,
            filterable=True,
            facetable=True,
            analyzer_name="keyword"
        ),
        SearchableField(
            name="table_name",
            type=SearchFieldDataType.String,
            filterable=True,
            sortable=True,
            analyzer_name="keyword"
        ),
        SearchableField(
            name="qualified_name",
            type=SearchFieldDataType.String,
            filterable=True,
            analyzer_name="keyword"
        ),
        SearchableField(
            name="description",
            type=SearchFieldDataType.String,
            analyzer_name="en.microsoft"
        ),
        SearchableField(
            name="column_names",
            type=SearchFieldDataType.String,
            collection=True,
            analyzer_name="keyword"
        ),
        SearchableField(
            name="column_descriptions",
            type=SearchFieldDataType.String,
            analyzer_name="en.microsoft"
        ),
        SearchableField(
            name="searchable_content",
            type=SearchFieldDataType.String,
            analyzer_name="en.microsoft"
        ),
        SimpleField(
            name="row_count",
            type=SearchFieldDataType.Int64,
            filterable=True,
            sortable=True
        ),
        SimpleField(
            name="column_count",
            type=SearchFieldDataType.Int32,
            filterable=True,
            sortable=True
        ),
    ]

    # Configure semantic search for better relevance
    semantic_config = SemanticConfiguration(
        name="table-cards-semantic-config",
        prioritized_fields=SemanticPrioritizedFields(
            title_field=SemanticField(field_name="qualified_name"),
            content_fields=[
                SemanticField(field_name="description"),
                SemanticField(field_name="searchable_content"),
                SemanticField(field_name="column_descriptions")
            ],
            keywords_fields=[
                SemanticField(field_name="table_name"),
                SemanticField(field_name="schema_name")
            ]
        )
    )

    semantic_search = SemanticSearch(
        configurations=[semantic_config]
    )

    # Create the index
    index = SearchIndex(
        name=index_name,
        fields=fields,
        semantic_search=semantic_search
    )

    index_client.create_or_update_index(index)
    logger.info(f"Index '{index_name}' created successfully")


def prepare_table_card_document(table_card, card_index: int) -> dict:
    """
    Convert a TableCard model to a searchable document.

    Args:
        table_card: TableCard pydantic model
        card_index: Sequential index for generating unique IDs

    Returns:
        Dictionary formatted for Azure AI Search indexing
    """
    metadata = table_card.table_metadata

    # Extract column information
    column_names = [col.name for col in table_card.columns]
    column_descriptions = " ".join([
        f"{col.name}: {col.description}"
        for col in table_card.columns
        if col.description
    ])

    # Build comprehensive searchable content combining all text fields
    searchable_parts = [
        metadata.name,
        metadata.description,
    ]

    # Add foreign key information for context
    if metadata.foreign_keys:
        fk_text = " ".join([
            f"Foreign key to {fk.references.schema_name}.{fk.references.table}"
            for fk in metadata.foreign_keys
        ])
        searchable_parts.append(fk_text)

    # Add column info
    searchable_parts.append(column_descriptions)

    searchable_content = " ".join(filter(None, searchable_parts))

    return {
        "id": f"{metadata.schema_name}_{metadata.name}_{card_index}",
        "schema_name": metadata.schema_name,
        "table_name": metadata.name,
        "qualified_name": metadata.qualified_name,
        "description": metadata.description or "",
        "column_names": column_names,
        "column_descriptions": column_descriptions,
        "searchable_content": searchable_content,
        "row_count": metadata.row_count or 0,
        "column_count": len(table_card.columns),
    }


def index_table_cards(
    endpoint: str,
    admin_key: str,
    index_name: str,
    settings: Settings
) -> None:
    """
    Load and index all table cards from the configured directory.

    Args:
        endpoint: Azure AI Search endpoint URL
        admin_key: Admin key for indexing operations
        index_name: Name of the index to populate
        settings: Application settings for loading table cards
    """
    logger.info("Loading table cards from disk...")
    table_cards = load_table_cards(settings)

    if not table_cards:
        logger.warning("No table cards found to index")
        return

    logger.info(f"Preparing {len(table_cards)} table cards for indexing...")

    # Convert table cards to search documents
    documents = [
        prepare_table_card_document(card, idx)
        for idx, card in enumerate(table_cards)
    ]

    # Upload to Azure AI Search
    logger.info(f"Uploading documents to index '{index_name}'...")
    search_client = SearchClient(
        endpoint,
        index_name,
        AzureKeyCredential(admin_key)
    )

    result = search_client.upload_documents(documents=documents)

    # Check for any failures
    succeeded = sum(1 for r in result if r.succeeded)
    failed = len(result) - succeeded

    if failed > 0:
        logger.warning(f"{failed} documents failed to index")
        for r in result:
            if not r.succeeded:
                logger.error(f"Failed to index {r.key}: {r.error_message}")

    logger.info(f"Successfully indexed {succeeded}/{len(documents)} table cards")


def main():
    """Main entry point for index setup."""
    settings = Settings()

    if not settings.azure_search:
        logger.error(
            "Azure AI Search is not configured. Please set the following environment variables:\n"
            "  - AZURE_SEARCH_ENDPOINT\n"
            "  - AZURE_SEARCH_ADMIN_KEY\n"
            "  - AZURE_SEARCH_QUERY_KEY\n"
            "  - AZURE_SEARCH_TABLE_CARDS_INDEX (optional, defaults to 'sql_assistant_table_cards_index')"
        )
        return

    endpoint = str(settings.azure_search.endpoint)
    admin_key = settings.azure_search.admin_key
    index_name = settings.azure_search.table_cards_index_name

    logger.info(f"Azure AI Search Endpoint: {endpoint}")
    logger.info(f"Index Name: {index_name}")

    # Create the index
    create_table_cards_index(endpoint, admin_key, index_name)

    # Index the table cards
    index_table_cards(endpoint, admin_key, index_name, settings)

    logger.info("\n" + "="*60)
    logger.info("    Index setup complete!")
    logger.info(f"   Index: {index_name}")
    logger.info(f"   Endpoint: {endpoint}")
    logger.info("="*60)


if __name__ == "__main__":
    main()
