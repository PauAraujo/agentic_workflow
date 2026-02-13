from pydantic import BaseModel, Field


class TableCardSearchResult(BaseModel):
    """Result from Azure AI Search for a single table card."""

    id: str
    schema_name: str
    table_name: str
    qualified_name: str
    score: float = Field(description="Relevance score from Azure AI Search")
    reranker_score: float | None = Field(
        default=None, description="Semantic reranker score if available"
    )
