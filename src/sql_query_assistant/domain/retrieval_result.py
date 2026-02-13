from pydantic import BaseModel, ConfigDict, Field


class RetrievalResult(BaseModel):
    """
    Result of the table card retrieval stage.

    Captures the intermediate and final results of the retrieval pipeline:
    1. Initial search (search_top_k candidates)
    2. Semantic reranking (reranker_top_k selection)
    3. FK expansion (related tables added)
    4. Final result (union of reranked + expanded)

    This provides full visibility into the retrieval pipeline for debugging,
    auditing, and tuning retrieval parameters.
    """

    model_config = ConfigDict(frozen=True)

    tables_from_search: list[str] = Field(
        default_factory=list,
        description="Tables returned from initial search (search_top_k candidates)",
    )
    tables_after_rerank: list[str] = Field(
        default_factory=list,
        description="Tables selected after semantic reranking (reranker_top_k)",
    )
    tables_from_fk_expansion: list[str] = Field(
        default_factory=list, description="Tables added via FK relationship expansion"
    )
    tables_final: list[str] = Field(
        default_factory=list, description="Final table list (reranked + FK expanded)"
    )
