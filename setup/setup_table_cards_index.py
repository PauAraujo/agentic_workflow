import logging

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ResourceNotFoundError
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

# Analyzer constants
ANALYZER_ENGLISH = "en.microsoft"
ANALYZER_KEYWORD = "keyword"

# Semantic configuration name
SEMANTIC_CONFIG_NAME = "table-cards-semantic-config"

# Field names
FIELD_ID = "id"
FIELD_SCHEMA_NAME = "schema_name"
FIELD_TABLE_NAME = "table_name"
FIELD_QUALIFIED_NAME = "qualified_name"
FIELD_DESCRIPTION = "description"
FIELD_COLUMN_NAMES = "column_names"
FIELD_COLUMN_DESCRIPTIONS = "column_descriptions"
FIELD_SEARCHABLE_CONTENT = "searchable_content"
FIELD_ROW_COUNT = "row_count"
FIELD_COLUMN_COUNT = "column_count"

# ID sanitization
UNSAFE_ID_CHARS = ['$', '.', '/', '\\', '#', '?']
SAFE_ID_REPLACEMENT = '_'


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

    # Check if index exists
    index_exists = False
    try:
        logger.info(f"Checking if index '{index_name}' exists...")
        index_client.get_index(index_name)
        index_exists = True
        logger.info(f"Index '{index_name}' already exists")
    except ResourceNotFoundError:
        logger.info(f"Index '{index_name}' does not exist")

    # Handle based on delete_if_exists flag
    if index_exists:
        if delete_if_exists:
            logger.info(f"Deleting existing index '{index_name}'...")
            index_client.delete_index(index_name)
            logger.info(f"Index '{index_name}' deleted successfully")
        else:
            logger.warning(
                f"Index '{index_name}' already exists and delete_if_exists=False. "
                "Skipping index creation to avoid unintended schema changes."
            )
            return

    logger.info(f"Creating index '{index_name}'...")

    # Define the index schema
    fields = [
        SimpleField(
            name=FIELD_ID,
            type=SearchFieldDataType.String,
            key=True,
            filterable=True,
            sortable=True
        ),
        SearchableField(
            name=FIELD_SCHEMA_NAME,
            type=SearchFieldDataType.String,
            filterable=True,
            facetable=True,
            analyzer_name=ANALYZER_KEYWORD
        ),
        SearchableField(
            name=FIELD_TABLE_NAME,
            type=SearchFieldDataType.String,
            filterable=True,
            sortable=True,
            analyzer_name=ANALYZER_KEYWORD
        ),
        SearchableField(
            name=FIELD_QUALIFIED_NAME,
            type=SearchFieldDataType.String,
            filterable=True,
            analyzer_name=ANALYZER_KEYWORD
        ),
        SearchableField(
            name=FIELD_DESCRIPTION,
            type=SearchFieldDataType.String,
            analyzer_name=ANALYZER_ENGLISH
        ),
        SearchableField(
            name=FIELD_COLUMN_NAMES,
            type=SearchFieldDataType.String,
            collection=True,
            analyzer_name=ANALYZER_KEYWORD
        ),
        SearchableField(
            name=FIELD_COLUMN_DESCRIPTIONS,
            type=SearchFieldDataType.String,
            analyzer_name=ANALYZER_ENGLISH
        ),
        SearchableField(
            name=FIELD_SEARCHABLE_CONTENT,
            type=SearchFieldDataType.String,
            analyzer_name=ANALYZER_ENGLISH
        ),
        SimpleField(
            name=FIELD_ROW_COUNT,
            type=SearchFieldDataType.Int64,
            filterable=True,
            sortable=True
        ),
        SimpleField(
            name=FIELD_COLUMN_COUNT,
            type=SearchFieldDataType.Int32,
            filterable=True,
            sortable=True
        ),
    ]

    # Configure semantic search for better relevance
    semantic_config = SemanticConfiguration(
        name=SEMANTIC_CONFIG_NAME,
        prioritized_fields=SemanticPrioritizedFields(
            title_field=SemanticField(field_name=FIELD_QUALIFIED_NAME),
            content_fields=[
                SemanticField(field_name=FIELD_DESCRIPTION),
                SemanticField(field_name=FIELD_SEARCHABLE_CONTENT),
                SemanticField(field_name=FIELD_COLUMN_DESCRIPTIONS)
            ],
            keywords_fields=[
                SemanticField(field_name=FIELD_TABLE_NAME),
                SemanticField(field_name=FIELD_SCHEMA_NAME)
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

    # Sanitize ID to only contain allowed characters (letters, digits, _, -, =)
    # Azure AI Search document keys cannot contain $, ., or other special characters
    safe_schema = metadata.schema_name
    safe_table = metadata.name
    for char in UNSAFE_ID_CHARS:
        safe_schema = safe_schema.replace(char, SAFE_ID_REPLACEMENT)
        safe_table = safe_table.replace(char, SAFE_ID_REPLACEMENT)
    document_id = f"{safe_schema}_{safe_table}_{card_index}"

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
        FIELD_ID: document_id,
        FIELD_SCHEMA_NAME: metadata.schema_name,
        FIELD_TABLE_NAME: metadata.name,
        FIELD_QUALIFIED_NAME: metadata.qualified_name,
        FIELD_DESCRIPTION: metadata.description or "",
        FIELD_COLUMN_NAMES: column_names,
        FIELD_COLUMN_DESCRIPTIONS: column_descriptions,
        FIELD_SEARCHABLE_CONTENT: searchable_content,
        FIELD_ROW_COUNT: metadata.row_count or 0,
        FIELD_COLUMN_COUNT: len(table_card.columns),
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
