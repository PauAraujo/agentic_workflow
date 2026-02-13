import logging

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient

from sql_query_assistant.config import Settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def verify_index():
    """Verify the index has documents and can be searched."""
    settings = Settings()

    if not settings.azure_search:
        logger.error("Azure AI Search is not configured")
        return

    endpoint = str(settings.azure_search.endpoint)
    query_key = settings.azure_search.query_key
    index_name = settings.azure_search.table_cards_index_name

    search_client = SearchClient(endpoint, index_name, AzureKeyCredential(query_key))

    # Get document count
    try:
        results = search_client.search(search_text="*", include_total_count=True)
        count = results.get_count()
        logger.info(f"Index '{index_name}' contains {count} documents")

        # Try a simple search
        results = search_client.search(search_text="patient", top=3)
        logger.info("\nSample search for 'patient':")
        for i, result in enumerate(results, 1):
            logger.info(
                f"  {i}. {result['qualified_name']}: {result.get('description', 'No description')[:100]}"
            )
            if i >= 3:
                break

    except Exception as e:
        logger.error(f"Error querying index: {e}")


if __name__ == "__main__":
    verify_index()
