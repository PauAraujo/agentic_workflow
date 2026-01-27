from pydantic import BaseModel, ConfigDict, Field
from typing import Any, ClassVar, Literal, TYPE_CHECKING

from sql_query_assistant.domain.retrieval_result import RetrievalResult
from sql_query_assistant.config import AgentSettings, TableSelectorSettings
from sql_query_assistant.domain.table_selection import (
    TableSelectionDecision,
    TableSelectionResponse,
)
if TYPE_CHECKING:
    from sql_query_assistant.config import Settings
    from sql_query_assistant.state import WorkflowState


class RetrievalConfigSnapshot(BaseModel):
    """Configuration snapshot for retrieval settings."""

    model_config = ConfigDict(frozen=True)

    hybrid_search_enabled: bool
    search_top_k: int
    reranker_top_k: int
    fk_expansion_enabled: bool
    fk_expansion_source_count: int
    fk_expansion_max_total: int
    fk_expansion_include_reverse: bool
    schema_filter: list[str] | None = None


class ConfigSnapshot(BaseModel):
    """Complete configuration snapshot for a run."""

    model_config = ConfigDict(frozen=True)

    target_sql_dialect: str
    max_repair_attempts: int
    total_available_tables: int
    agents: AgentSettings
    table_selector: TableSelectorSettings
    retrieval: RetrievalConfigSnapshot | None = None


class SQLAttempt(BaseModel):
    """A single SQL drafting or repair attempt."""

    model_config = ConfigDict(frozen=True)

    attempt: int
    type: Literal["draft", "repair"]
    sql: str
    rationale: str
    tables_used: list[str] = Field(default_factory=list)
    validation_passed: bool
    validation_errors: list[str] = Field(default_factory=list)


class DraftingAndValidation(BaseModel):
    """Summary of SQL drafting and validation attempts."""

    model_config = ConfigDict(frozen=True)

    attempts: list[SQLAttempt] = Field(default_factory=list)
    final_sql: str | None = None
    final_validation_passed: bool = False

    @property
    def repair_count(self) -> int:
        """Number of repair attempts (attempts with type='repair')."""
        return sum(1 for attempt in self.attempts if attempt.type == "repair")

    @property
    def first_validation_passed(self) -> bool:
        """Whether the first draft passed validation."""
        return self.attempts[0].validation_passed if self.attempts else False

    @property
    def tables_used_count(self) -> int:
        """Number of tables used in the final attempt."""
        return len(self.attempts[-1].tables_used) if self.attempts else 0


class ExecutionSummary(BaseModel):
    """Summary of SQL execution results."""

    model_config = ConfigDict(frozen=True)

    attempted: bool = False
    succeeded: bool = False
    row_count: int | None = None
    error: str | None = None
    duration_ms: float | None = None


class RunRecord(BaseModel):
    """
    Complete record of a workflow run.

    This is the main persistence model, containing all information about
    a single text-to-SQL workflow execution. The JSON serialization of
    this model is the source of truth for run data.
    """

    model_config = ConfigDict(frozen=True)

    # CSV column names - single source of truth for CSV schema
    CSV_FIELDNAMES: ClassVar[list[str]] = [
        "run_id",
        "timestamp",
        "user_query",
        # Retrieval
        "num_tables_retrieved",
        "num_tables_selected",
        "num_tables_used",
        # Models
        "drafter_provider",
        "drafter_model",
        "repairer_provider",
        "repairer_model",
        # SQL output
        "final_sql",
        "sql_dialect",
        # Validation/repair
        "first_validation_passed",
        "repair_count",
        "final_validation_passed",
        # Execution
        "execution_succeeded",
        "row_count",
    ]

    run_id: str = Field(description="Timestamp-based ID: YYYYMMDD_HHMMSS_ffffff")
    timestamp: str = Field(description="ISO format timestamp")
    user_query: str
    config: ConfigSnapshot
    retrieval: RetrievalResult
    selection: TableSelectionResponse
    drafting_and_validation: DraftingAndValidation
    execution: ExecutionSummary

    @classmethod
    def from_state(
        cls,
        state: "WorkflowState",
        settings: "Settings",
        run_id: str,
        timestamp: str,
    ) -> "RunRecord":
        """
        Build a RunRecord from workflow state and settings.

        Args:
            state: Complete workflow state after execution
            settings: Application settings
            run_id: Timestamp-based run ID
            timestamp: ISO format timestamp

        Returns:
            Complete RunRecord instance
        """
        # Build config snapshot
        all_table_cards = state.get("all_table_cards", [])
        allowed_schemas = state.get("allowed_schemas")

        retrieval_config = None
        if settings.azure_search:
            retrieval_config = RetrievalConfigSnapshot(
                hybrid_search_enabled=settings.azure_search.hybrid_search_enabled,
                search_top_k=settings.azure_search.top_k,
                reranker_top_k=settings.azure_search.reranker_top_k,
                fk_expansion_enabled=settings.azure_search.fk_expansion_enabled,
                fk_expansion_source_count=settings.azure_search.fk_expansion_source_count,
                fk_expansion_max_total=settings.azure_search.fk_expansion_max_total,
                fk_expansion_include_reverse=settings.azure_search.fk_expansion_include_reverse,
                schema_filter=allowed_schemas,
            )

        config = ConfigSnapshot(
            target_sql_dialect=settings.target_sql_dialect,
            max_repair_attempts=settings.max_repair_attempts,
            total_available_tables=len(all_table_cards),
            agents=settings.agents,
            table_selector=settings.table_selector,
            retrieval=retrieval_config,
        )

        retrieval = state["retrieval_result"]

        # Build selection summary
        table_cards_with_selection = state.get("table_cards_with_selection", [])
        selection = TableSelectionResponse(
            selected_tables=[
                TableSelectionDecision(
                    qualified_name=selected.table_card.table_metadata.qualified_name,
                    selection_reason=selected.selection_reason,
                    key_columns=selected.key_columns,
                )
                for selected in table_cards_with_selection
            ],
            rationale=state.get("selection_rationale"),
        )

        # Build drafting and validation summary
        drafting_and_validation = cls._build_drafting_and_validation(state)

        # Build execution summary
        query_result = state.get("query_result")
        execution = ExecutionSummary(
            attempted=query_result is not None and not query_result.validation_failed,
            succeeded=query_result.success if query_result else False,
            row_count=query_result.row_count if query_result else None,
            error=query_result.error_message if query_result else None,
            duration_ms=query_result.execution_time_ms if query_result else None,
        )

        return cls(
            run_id=run_id,
            timestamp=timestamp,
            user_query=state.get("user_query", ""),
            config=config,
            retrieval=retrieval,
            selection=selection,
            drafting_and_validation=drafting_and_validation,
            execution=execution,
        )

    @staticmethod
    def _build_drafting_and_validation(state: "WorkflowState") -> DraftingAndValidation:
        """
        Build the drafting_and_validation section with attempt history.

        Data model:
        - sql_draft: The current/final SQL draft
        - repair_history: [original_draft, repair1, repair2, ...] if repairs occurred, else []
        - validation_result: Validation of the FINAL sql_draft only

        When repairs occur, repair_history[-1] == sql_draft

        TODO: Intermediate validation errors are not preserved
        Currently, only the final attempt's errors are saved
        """
        sql_draft = state.get("sql_draft")
        repair_history = state.get("repair_history", [])
        validation_result = state.get("validation_result")

        if not sql_draft:
            return DraftingAndValidation(
                attempts=[],
                final_sql=None,
                final_validation_passed=False,
            )

        final_passed = validation_result.is_valid if validation_result else False
        final_errors = (
            validation_result.get_all_errors()
            if validation_result and not final_passed
            else []
        )

        attempts = []

        if not repair_history:
            # Simple case: first draft passed (or failed without repair attempt)
            attempts.append(SQLAttempt(
                attempt=1,
                type="draft",
                sql=sql_draft.sql,
                rationale=sql_draft.rationale,
                tables_used=sql_draft.tables_used,
                validation_passed=final_passed,
                validation_errors=final_errors,
            ))
        else:
            # Repairs occurred: repair_history = [original_draft, repair1, repair2, ...]
            # First entry is the original draft that failed validation
            attempts.append(SQLAttempt(
                attempt=1,
                type="draft",
                sql=repair_history[0].sql,
                rationale=repair_history[0].rationale,
                tables_used=repair_history[0].tables_used,
                validation_passed=False,  # Failed validation, otherwise no repair
                validation_errors=[],  # Intermediate errors not preserved in state
            ))

            # Subsequent entries are repair attempts
            for i, repair_draft in enumerate(repair_history[1:], start=2):
                is_final = (i == len(repair_history))
                attempts.append(SQLAttempt(
                    attempt=i,
                    type="repair",
                    sql=repair_draft.sql,
                    rationale=repair_draft.rationale,
                    tables_used=repair_draft.tables_used,
                    validation_passed=is_final and final_passed,
                    validation_errors=final_errors if is_final and not final_passed else [],
                ))

        return DraftingAndValidation(
            attempts=attempts,
            final_sql=sql_draft.sql,
            final_validation_passed=final_passed,
        )

    def to_csv_row(self) -> dict[str, Any]:
        """
        Convert this record to a CSV row dictionary.

        Returns:
            Dictionary with keys matching CSV_FIELDNAMES
        """
        dv = self.drafting_and_validation
        has_repairs = dv.repair_count > 0

        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "user_query": self.user_query,
            # retrieval counts
            "num_tables_retrieved": len(self.retrieval.tables_final),
            "num_tables_selected": len(self.selection.selected_tables),
            "num_tables_used": dv.tables_used_count,
            # models
            "drafter_provider": self.config.agents.drafter.provider,
            "drafter_model": self.config.agents.drafter.model_name,
            "repairer_provider": self.config.agents.repairer.provider if has_repairs else "",
            "repairer_model": self.config.agents.repairer.model_name if has_repairs else "",
            # SQL output
            "final_sql": dv.final_sql or "",
            "sql_dialect": self.config.target_sql_dialect,
            # validation/repair
            "first_validation_passed": dv.first_validation_passed,
            "repair_count": dv.repair_count,
            "final_validation_passed": dv.final_validation_passed,
            # execution
            "execution_succeeded": self.execution.succeeded,
            "row_count": self.execution.row_count or 0,
        }
