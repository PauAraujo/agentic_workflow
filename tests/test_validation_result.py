import pytest

from sql_query_assistant.domain import ValidationResult


@pytest.mark.parametrize(
    "syntax_errors,explain_errors,expected_valid,expected_syntax_passed,expected_explain_passed",
    [
        pytest.param([], [], True, True, True, id="no_errors"),
        pytest.param(["Expected table name"], [], False, False, True, id="syntax_errors_only"),
        pytest.param([], ["no such table: NONEXISTENT_TABLE"], False, True, False, id="explain_errors_only"),
        pytest.param(["Invalid syntax"], ["Cannot execute malformed query"], False, False, False, id="both_error_types"),
    ],
)
def test_validation_result_computed_fields(
    syntax_errors, explain_errors, expected_valid, expected_syntax_passed, expected_explain_passed
):
    """Test ValidationResult computed fields with various error combinations."""
    result = ValidationResult(
        original_sql="SELECT * FROM TEST",
        syntax_errors=syntax_errors,
        explain_errors=explain_errors,
    )

    assert result.is_valid == expected_valid
    assert result.sqlglot_parse_passed == expected_syntax_passed
    assert result.explain_passed == expected_explain_passed


def test_get_all_errors_combines_both_types():
    """get_all_errors should combine syntax and explain errors."""
    result = ValidationResult(
        original_sql="SELECT * FROM test",
        syntax_errors=["Syntax error 1", "Syntax error 2"],
        explain_errors=["Explain error 1"],
    )

    all_errors = result.get_all_errors()

    assert len(all_errors) == 3
    assert "Syntax error 1" in all_errors
    assert "Syntax error 2" in all_errors
    assert "Explain error 1" in all_errors


@pytest.mark.parametrize(
    "syntax_errors,explain_errors,expected_patterns",
    [
        pytest.param(
            ["Expected table name", "Invalid WHERE clause"],
            [],
            ["syntax errors", "Expected table name", "Invalid WHERE clause"],
            id="syntax_errors_only",
        ),
        pytest.param(
            [],
            ["no such table: NONEXISTENT"],
            ["explain errors", "no such table: NONEXISTENT"],
            id="explain_errors_only",
        ),
        pytest.param(
            ["Bad syntax"],
            ["Cannot parse"],
            ["syntax errors", "explain errors", "Bad syntax", "Cannot parse"],
            id="both_error_types",
        ),
        pytest.param(
            [],
            [],
            ["no errors", "validation passed"],
            id="success_message",
        ),
    ],
)
def test_get_error_summary_formatting(syntax_errors, explain_errors, expected_patterns):
    """Test get_error_summary formats errors correctly."""
    result = ValidationResult(
        original_sql="SELECT * FROM TEST",
        syntax_errors=syntax_errors,
        explain_errors=explain_errors,
    )

    summary = result.get_error_summary()

    for pattern in expected_patterns:
        assert pattern.lower() in summary.lower(), f"Expected '{pattern}' in summary"
