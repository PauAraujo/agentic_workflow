import logging

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ResourceNotFoundError
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    HnswParameters,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SearchableField,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)
from openai import AzureOpenAI

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

# Noise suffixes that add no semantic value (high frequency, low meaning)
SUFFIX_NOISE_TOKENS = {'id', 'code', 'key', 'num', 'pk', 'fk', 'flag', 'ind'}

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
FIELD_NORMALIZED_COLUMN_NAMES = "normalized_column_names"
FIELD_CONTENT_VECTOR = "content_vector"

# Vector search configuration
VECTOR_ALGORITHM_NAME = "hnsw-algorithm"
VECTOR_PROFILE_NAME = "vector-profile"

# ID sanitization
UNSAFE_ID_CHARS = ['$', '.', '/', '\\', '#', '?']
SAFE_ID_REPLACEMENT = '_'


def create_table_cards_index(
    endpoint: str,
    admin_key: str,
    index_name: str,
    embedding_dimensions: int = 1536,
    delete_if_exists: bool = True
) -> None:
    """
    Create the table cards search index with appropriate schema.

    Args:
        endpoint: Azure AI Search endpoint URL
        admin_key: Admin key for creating/updating indexes
        index_name: Name of the index to create
        embedding_dimensions: Dimension of embedding vectors (1536 for text-embedding-3-small)
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
        SimpleField(  # not searchable, only used for filtering, sorting or facets
            name=FIELD_ID,
            type=SearchFieldDataType.String,
            key=True,
            filterable=True,
            sortable=True
        ),
        SearchableField(  # lexical field (exact match)
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
        SearchableField( # lexical field ("BM25" search layer)
            name=FIELD_DESCRIPTION,
            type=SearchFieldDataType.String,
            analyzer_name=ANALYZER_ENGLISH # tokenizes, stems, removes stop words, case-insensitive
        ),
        SearchableField(
            name=FIELD_COLUMN_NAMES,
            type=SearchFieldDataType.String,
            collection=True,
            analyzer_name=ANALYZER_KEYWORD
        ),
        SearchableField(
            name=FIELD_NORMALIZED_COLUMN_NAMES,
            type=SearchFieldDataType.String,
            analyzer_name=ANALYZER_ENGLISH
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
        # Vector field for semantic similarity search
        SearchField(
            name=FIELD_CONTENT_VECTOR,
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=embedding_dimensions,
            vector_search_profile_name=VECTOR_PROFILE_NAME
        ),
    ]

    # Vector search configuration using HNSW algorithm
    # HNSW provides excellent recall with efficient search (better than exhaustive KNN for our scale)
    vector_search = VectorSearch(
        algorithms=[
            HnswAlgorithmConfiguration(
                name=VECTOR_ALGORITHM_NAME,
                parameters=HnswParameters(
                    m=4,  # Number of bi-directional links (4 is good for <1000 docs)
                    ef_construction=400,  # Higher = better recall during indexing
                    ef_search=500,  # Higher = better recall during search
                    metric="cosine"  # Cosine similarity for normalized embeddings
                )
            )
        ],
        profiles=[
            VectorSearchProfile(
                name=VECTOR_PROFILE_NAME,
                algorithm_configuration_name=VECTOR_ALGORITHM_NAME
            )
        ]
    )

    # Semantic re-ranking configuration
    # 1. System performs standard Text Search (BM25) to get top 50 results.
    # 2. System feeds the text from 'prioritized_fields' into a Microsoft Deep Learning model.
    # 3. Model re-orders results based on reading comprehension, not just keyword frequency.
    semantic_config = SemanticConfiguration(
        name=SEMANTIC_CONFIG_NAME,
        prioritized_fields=SemanticPrioritizedFields( # high importance
            title_field=SemanticField(field_name=FIELD_QUALIFIED_NAME),
            content_fields=[ # medium importance
                SemanticField(field_name=FIELD_SEARCHABLE_CONTENT),
                SemanticField(field_name=FIELD_NORMALIZED_COLUMN_NAMES),
                SemanticField(field_name=FIELD_COLUMN_DESCRIPTIONS)
            ],
            keywords_fields=[ # low importance
                SemanticField(field_name=FIELD_TABLE_NAME),
                SemanticField(field_name=FIELD_SCHEMA_NAME)
            ]
        )
    )

    semantic_search = SemanticSearch(
        configurations=[semantic_config]
    )

    # Create the index with vector search and semantic reranking
    index = SearchIndex(
        name=index_name,
        fields=fields,
        vector_search=vector_search,
        semantic_search=semantic_search
    )

    index_client.create_or_update_index(index)
    logger.info(f"Index '{index_name}' created successfully")


def create_embedding_client(settings: Settings) -> AzureOpenAI:
    """
    Create an Azure OpenAI client for generating embeddings.

    Args:
        settings: Application settings with Azure OpenAI configuration

    Returns:
        Configured AzureOpenAI client
    """
    return AzureOpenAI(
        api_key=settings.azure.api_key,
        api_version=settings.azure.api_version,
        azure_endpoint=str(settings.azure.openai_endpoint)
    )


def generate_embeddings(
    client: AzureOpenAI,
    texts: list[str],
    deployment: str,
    batch_size: int = 16
) -> list[list[float]]:
    """
    Generate embeddings for a list of texts using Azure OpenAI.

    Args:
        client: Azure OpenAI client
        texts: List of texts to embed
        deployment: Azure OpenAI deployment name for embeddings
        batch_size: Number of texts to embed per API call

    Returns:
        List of embedding vectors
    """
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        logger.debug(f"Generating embeddings for batch {i // batch_size + 1}")

        response = client.embeddings.create(
            input=batch,
            model=deployment
        )

        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)

    return all_embeddings


def normalize_column_name(column_name: str) -> str:
    """
    Normalize a column name for searchability.

    Splits on underscores and removes noise suffixes only (e.g., _ID, _CODE).
    Preserves semantic tokens like DATE, TIME, NAME, TYPE, STATUS.

    Examples:
        PATIENT_SEX_ID -> "patient sex"
        BIRTH_DATE -> "birth date"
        SUBSTANCE_NAME -> "substance name"
        RMS_CODE -> "rms"
        START_DATE -> "start date"

    Args:
        column_name: Raw column name (e.g., "PATIENT_SEX_ID")

    Returns:
        Normalized column name (e.g., "patient sex")
    """
    # Split on underscores and convert to lowercase
    tokens = column_name.lower().split('_')

    # Strip only if last token is noise AND there are multiple tokens
    if len(tokens) > 1 and tokens[-1] in SUFFIX_NOISE_TOKENS:
        tokens = tokens[:-1]

    return ' '.join(tokens)

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

    # Normalize column names for better searchability
    normalized_column_names = [
        normalize_column_name(col_name)
        for col_name in column_names
    ]
    # Filter out empty normalized names
    normalized_column_names_text = " ".join(filter(None, normalized_column_names))

    # Build comprehensive searchable content combining all text fields
    searchable_parts = [
        metadata.name,
        metadata.description,
    ]

    # Add normalized column names
    if normalized_column_names_text:
        searchable_parts.append(normalized_column_names_text)

    # Add foreign key information from column-level references
    column_fk_parts = []
    for col in table_card.columns:
        if col.references:
            ref = col.references
            column_fk_parts.append(
                f"{col.name} references {ref.schema_name}.{ref.table}.{ref.column}"
            )
    if column_fk_parts:
        searchable_parts.append(" ".join(column_fk_parts))

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
        FIELD_NORMALIZED_COLUMN_NAMES: normalized_column_names_text,
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

    Generates embeddings for each table card's searchable content and uploads
    documents with both text fields and vector embeddings.

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

    # Generate embeddings for searchable content
    embedding_deployment = settings.azure_search.embedding_deployment
    logger.info(f"Generating embeddings using deployment '{embedding_deployment}'...")

    embedding_client = create_embedding_client(settings)
    searchable_contents = [doc[FIELD_SEARCHABLE_CONTENT] for doc in documents]

    embeddings = generate_embeddings(
        client=embedding_client,
        texts=searchable_contents,
        deployment=embedding_deployment
    )

    # Add embeddings to documents
    for doc, embedding in zip(documents, embeddings):
        doc[FIELD_CONTENT_VECTOR] = embedding

    logger.info(f"Generated {len(embeddings)} embeddings")

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

    embedding_dimensions = settings.azure_search.embedding_dimensions

    logger.info(f"Azure AI Search Endpoint: {endpoint}")
    logger.info(f"Index Name: {index_name}")
    logger.info(f"Embedding Dimensions: {embedding_dimensions}")

    # Create the index with vector search support
    create_table_cards_index(
        endpoint,
        admin_key,
        index_name,
        embedding_dimensions=embedding_dimensions
    )

    # Index the table cards with embeddings
    index_table_cards(endpoint, admin_key, index_name, settings)

    logger.info("\n" + "="*60)
    logger.info("    Index setup complete!")
    logger.info(f"   Index: {index_name}")
    logger.info(f"   Endpoint: {endpoint}")
    logger.info("="*60)


if __name__ == "__main__":
    main()
