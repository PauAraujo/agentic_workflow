from pydantic import BaseModel, Field, computed_field


class ValidationResult(BaseModel):
    """Result of validating a SQL query before execution."""

    original_sql: str = Field(..., description="SQL query from drafter")

    # Validation errors (source of truth)
    syntax_errors: list[str] = Field(
        default_factory=list, description="Syntax errors from SQLGlot parsing"
    )
    explain_errors: list[str] = Field(
        default_factory=list, description="Errors from EXPLAIN dry-run"
    )

    @computed_field
    @property
    def sqlglot_parse_passed(self) -> bool:
        """SQLGlot successfully parsed the SQL."""
        return len(self.syntax_errors) == 0

    @computed_field
    @property
    def explain_passed(self) -> bool:
        """EXPLAIN query succeeded."""
        return len(self.explain_errors) == 0

    @computed_field
    @property
    def is_valid(self) -> bool:
        """Whether the SQL passed all validation checks."""
        return self.sqlglot_parse_passed and self.explain_passed

    def get_all_errors(self) -> list[str]:
        """Get all validation errors combined."""
        return self.syntax_errors + self.explain_errors

    def get_error_summary(self) -> str:
        """Get a formatted summary of all errors."""
        if self.is_valid:
            return "No errors - validation passed"

        errors = []
        if self.syntax_errors:
            errors.append(f"Syntax errors: {'; '.join(self.syntax_errors)}")
        if self.explain_errors:
            errors.append(f"EXPLAIN errors: {'; '.join(self.explain_errors)}")

        return "\n".join(errors) if errors else "Unknown validation error"
