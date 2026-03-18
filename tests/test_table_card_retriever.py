import pytest

from unittest.mock import MagicMock, patch


def test_retrieve_raises_on_zero_search_results():
    """
    Verify that zero search results raises RuntimeError instead of silently
    falling back to loading all table cards.

    Zero hits from a semantic search index with 100+ documents could indicate
    infrastructure problems (misconfigured index, missing embeddings, etc.)
    that should be surfaced immediately.
    """
    # We import here to avoid loading Settings from .env at module level
    from sql_query_assistant.modules.table_card_retriever.nodes import (
        retrieve_relevant_table_cards,
    )

    state = {
        "user_query": "Find all adverse reactions for aspirin",
        "allowed_schemas": ["ICSR", "ICSR_LOOKUP"],
    }

    # Create mock settings to avoid .env loading
    mock_settings = MagicMock()
    mock_settings.azure_search.endpoint = "https://example.search.windows.net"
    mock_settings.azure_search.query_key = "dummy-key"
    mock_settings.azure_search.table_cards_index = "table-cards-index"
    mock_settings.azure_search.top_k = 10
    mock_settings.azure_search.hybrid_search_enabled = False

    # Mock SearchClient to return empty results
    mock_search_client = MagicMock()
    mock_search_client.search.return_value = iter([])  # Empty results

    with patch(
        "sql_query_assistant.modules.table_card_retriever.nodes.SearchClient",
        return_value=mock_search_client,
    ):
        with pytest.raises(RuntimeError) as exc_info:
            retrieve_relevant_table_cards(state, mock_settings)

        # Verify error message contains diagnostic info
        error_message = str(exc_info.value)
        assert "No relevant tables found" in error_message
        assert "aspirin" in error_message  # Query should be in message


def test_retrieve_error_message_includes_query_context():
    """Verify the RuntimeError includes enough context for debugging."""
    from sql_query_assistant.modules.table_card_retriever.nodes import (
        retrieve_relevant_table_cards,
    )

    long_query = "x" * 300  # Query longer than truncation limit
    state = {
        "user_query": long_query,
        "allowed_schemas": None,
    }

    mock_settings = MagicMock()
    mock_settings.azure_search.endpoint = "https://example.search.windows.net"
    mock_settings.azure_search.query_key = "dummy-key"
    mock_settings.azure_search.table_cards_index = "table-cards-index"
    mock_settings.azure_search.top_k = 10
    mock_settings.azure_search.hybrid_search_enabled = False

    mock_search_client = MagicMock()
    mock_search_client.search.return_value = iter([])

    with patch(
        "sql_query_assistant.modules.table_card_retriever.nodes.SearchClient",
        return_value=mock_search_client,
    ):
        with pytest.raises(RuntimeError) as exc_info:
            retrieve_relevant_table_cards(state, mock_settings)

        # Full query should be included in error message for debugging
        error_message = str(exc_info.value)
        assert long_query in error_message
