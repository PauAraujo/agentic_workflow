import re
import sys
import json
import argparse

from typing import Any
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_DIR = PROJECT_ROOT / "input" / "db_exports"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "input" / "exports_and_DDL" / "created_ddl"

# The schemas must be created in this order because later schemas reference
# tables defined in earlier ones (via foreign keys).
EXECUTION_ORDER = ["ICSR_LOOKUP", "ICSR", "ICSR_EMA"]

# Oracle column types that store character/string data and accept a length
# qualifier (e.g. VARCHAR2(100 CHAR)).
ORACLE_CHAR_TYPES = ("VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR")


def _format_column_type(column_metadata: dict[str, Any]) -> str:
    """
    Convert a column's metadata into its Oracle SQL type string.

    For example, a column with data_type="VARCHAR2", char_length=100, and
    char_used="C" becomes `VARCHAR2(100 CHAR)`. A NUMBER with precision=10
    and scale=2 becomes `NUMBER(10,2)`.

    Args:
        column_metadata: Dict with keys like "data_type", "data_precision",
            "data_scale", "char_length", "char_used", "data_length" — as
            exported from Oracle's ALL_TAB_COLUMNS view.

    Returns:
        The fully-qualified Oracle type string (e.g. "VARCHAR2(100 CHAR)").
    """
    data_type = column_metadata.get("data_type") or ""
    precision = column_metadata.get("data_precision")
    scale = column_metadata.get("data_scale")
    char_length = column_metadata.get("char_length")
    char_used = column_metadata.get("char_used")  # "C" = CHAR semantics, "B" = BYTE
    data_length = column_metadata.get("data_length")

    if data_type in ORACLE_CHAR_TYPES:
        length = char_length or data_length
        if length:
            semantics = " CHAR" if char_used == "C" else ""
            return f"{data_type}({length}{semantics})"
        return data_type

    if data_type == "NUMBER":
        if precision is not None:
            if scale is not None:
                return f"NUMBER({precision},{scale})"
            return f"NUMBER({precision})"
        return "NUMBER"

    if data_type == "RAW":
        if data_length:
            return f"RAW({data_length})"
        return "RAW"

    # for TIMESTAMP variants, DATE, CLOB, BLOB, etc. use as-is
    return data_type


def _is_identity_column(column_metadata: dict[str, Any]) -> bool:
    """
    Check whether a column is an auto-generated identity column.

    Identity columns have their values assigned automatically by the database
    (similar to "auto-increment" in other databases).
    """
    return column_metadata.get("identity_column") == "YES"


def _is_virtual_column(column_metadata: dict[str, Any]) -> bool:
    """
    Check whether a column is virtual (its value is computed from an expression).

    Heuristic: Oracle wraps column references in double quotes inside virtual column
    expressions (e.g. "COL_A"+"COL_B"), but regular defaults don't contain them.

    Args:
        column_metadata: Dict with column metadata, including "data_default" which
        may contain the defining expression for virtual columns.

    Returns:
        True if the column is likely virtual, False otherwise.
    """
    default_expression = column_metadata.get("data_default")
    if default_expression is None:
        return False
    # If default value contains double quote, treat column as virtual
    return '"' in default_expression


def _extract_schema_qualified_function(expression: str) -> str | None:
    """
    Extract a schema-qualified function reference from a column expression.

    Virtual columns sometimes call functions defined in a specific schema,
    written as `"SCHEMA_NAME"."FUNCTION_NAME"`.  This helper extracts that
    reference so we can warn the user that the function must exist before
    the DDL is executed.

    Returns:
        A string like "ICSR.FUNCTION_REGEXP_REPLACE", or None if no such
        reference was found.
    """
    match = re.search(r'"(\w+)"\."(FUNCTION_\w+)"', expression)
    if match:
        return f"{match.group(1)}.{match.group(2)}"
    return None


def _group_rows_by_key(rows: list[dict], key: str) -> dict[str, list[dict]]:
    """
    Group a list of dicts by the value of a shared key.

    Example::

        _group_rows_by_key(
            [{"name": "a", "v": 1}, {"name": "a", "v": 2}, {"name": "b", "v": 3}],
            "name",
        )
        # => {"a": [{"name": "a", "v": 1}, {"name": "a", "v": 2}],
        #     "b": [{"name": "b", "v": 3}]}
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row[key]].append(row)
    return dict(groups)


def _build_primary_key_info(
    constraints: list[dict], constraint_columns: list[dict]
) -> tuple[dict[str, list[str]], dict[str, str], dict[str, str]]:
    """
    Extract primary key information from the raw constraint metadata.

    A primary key (PK) uniquely identifies each row in a table.  A table has
    at most one PK, which may span one or more columns.

    Args:
        constraints: List of constraint dicts (from Oracle's ALL_CONSTRAINTS).
            Primary keys have constraint_type="P".
        constraint_columns: List of column-to-constraint mappings (from
            Oracle's ALL_CONS_COLUMNS), each with "constraint_name",
            "column_name", and "position".

    Returns:
        A 3-tuple of dicts, all keyed by table name:

        - pk_columns_by_table:  table -> ordered list of PK column names
        - pk_status_by_table:   table -> "ENABLED" or "DISABLED"
        - pk_name_by_table:     table -> the constraint name (e.g. "PK_CASE")
    """
    primary_key_constraints: dict[str, dict] = {}
    for constraint in constraints:
        if constraint["constraint_type"] == "P":
            primary_key_constraints[constraint["constraint_name"]] = constraint

    columns_by_constraint_name = _group_rows_by_key(constraint_columns, "constraint_name")

    pk_columns_by_table: dict[str, list[str]] = {}
    pk_status_by_table: dict[str, str] = {}
    pk_name_by_table: dict[str, str] = {}

    for constraint_name, constraint_info in primary_key_constraints.items():
        table_name = constraint_info["table_name"]
        ordered_columns = columns_by_constraint_name.get(constraint_name, [])
        ordered_columns.sort(key=lambda col: col.get("position") or 0)

        pk_columns_by_table[table_name] = [col["column_name"] for col in ordered_columns]
        pk_status_by_table[table_name] = constraint_info.get("status", "ENABLED")
        pk_name_by_table[table_name] = constraint_name

    return pk_columns_by_table, pk_status_by_table, pk_name_by_table


def _build_unique_constraint_info(
    constraints: list[dict], constraint_columns: list[dict]
) -> dict[str, list[tuple[str, list[str], str]]]:
    """
    Extract unique constraint information from the raw constraint metadata.

    A unique constraint ensures that no two rows share the same value(s) in
    the constrained column(s).  Unlike a primary key, a table can have
    multiple unique constraints.

    Args:
        constraints: List of constraint dicts.  Unique constraints have
            constraint_type="U".
        constraint_columns: Column-to-constraint mappings with
            "constraint_name", "column_name", and "position".

    Returns:
        Dict keyed by table name.  Each value is a list of
        `(constraint_name, [column_names], status)` tuples.
    """
    unique_constraints: dict[str, dict] = {}
    for constraint in constraints:
        if constraint["constraint_type"] == "U":
            unique_constraints[constraint["constraint_name"]] = constraint

    columns_by_constraint_name = _group_rows_by_key(constraint_columns, "constraint_name")

    unique_info_by_table: dict[str, list[tuple[str, list[str], str]]] = defaultdict(list)
    for constraint_name, constraint_info in unique_constraints.items():
        table_name = constraint_info["table_name"]
        ordered_columns = columns_by_constraint_name.get(constraint_name, [])
        ordered_columns.sort(key=lambda col: col.get("position") or 0)

        column_names = [col["column_name"] for col in ordered_columns]
        status = constraint_info.get("status", "ENABLED")
        unique_info_by_table[table_name].append((constraint_name, column_names, status))

    return dict(unique_info_by_table)


def _build_foreign_key_groups(
    foreign_keys: list[dict],
) -> dict[str, list[tuple[str, list[dict], str]]]:
    """
    Group foreign key metadata by source table.

    A foreign key (FK) links a column (or set of columns) in one table to the
    primary key of another table, enforcing referential integrity i.e. you
    can't insert a value that doesn't exist in the referenced table.

    Args:
        foreign_keys: List of FK dicts, each representing one column mapping
            within a FK constraint.  Multi-column FKs have multiple entries
            sharing the same "constraint_name".

    Returns:
        Dict keyed by source table name. Each value is a list of
        `(constraint_name, [column_mapping_rows], status)` tuples.
        The column_mapping_rows are sorted by position.
    """
    mappings_by_constraint: dict[str, list[dict]] = defaultdict(list)
    for fk_mapping in foreign_keys:
        mappings_by_constraint[fk_mapping["constraint_name"]].append(fk_mapping)

    fk_groups_by_table: dict[str, list[tuple[str, list[dict], str]]] = defaultdict(list)
    for constraint_name, column_mappings in mappings_by_constraint.items():
        column_mappings.sort(key=lambda mapping: mapping.get("position") or 0)
        source_table = column_mappings[0]["table_name"]
        status = column_mappings[0].get("status", "ENABLED")
        fk_groups_by_table[source_table].append((constraint_name, column_mappings, status))

    return dict(fk_groups_by_table)


def _find_required_function_warnings(columns: list[dict]) -> list[str]:
    """
    Find external functions that must exist before this DDL can run.

    Some virtual columns call functions defined in a specific schema
    (e.g. `"ICSR"."FUNCTION_REGEXP_REPLACE"`). These functions must be
    created before the DDL is executed, otherwise the CREATE TABLE will fail.

    Args:
        columns: List of column metadata dicts.

    Returns:
        Sorted list of `"SCHEMA.FUNCTION_NAME"` strings the DDL depends on.
    """
    required_functions: set[str] = set()
    for column_metadata in columns:
        # Identity columns (auto-increment) can have quoted expressions in
        # data_default (e.g. "SCHEMA"."ISEQ$$_123".nextval) that would
        # incorrectly pass the virtual-column heuristic. Skip them.
        if _is_identity_column(column_metadata):
            continue
        # Virtual columns store their defining expression in data_default.
        # Some of these expressions call functions from another schema
        # those functions must already exist when the DDL runs.
        if _is_virtual_column(column_metadata):
            function_reference = _extract_schema_qualified_function(column_metadata["data_default"])
            if function_reference:
                required_functions.add(function_reference)
    return sorted(required_functions)


def _generate_column_line(column_metadata: dict[str, Any]) -> str:
    """
    Generate one line of a CREATE TABLE body for a single column.

    Handles three mutually exclusive cases, checked in priority order:

    1. Identity columns: auto-incrementing, implicitly NOT NULL.
    2. Virtual columns: value is computed from an expression.
    3. Regular columns: may have a DEFAULT value and/or NOT NULL.

    Returns:
        A string like `'    REPORT_ID                        NUMBER(20) NOT NULL'`
        (indented, no trailing comma; the caller joins lines with commas).
    """
    name_pad = 35  # spaces to pad column names for visual alignment
    column_name = column_metadata["column_name"]
    column_type = _format_column_type(column_metadata)
    parts = [f"    {column_name:<{name_pad}}{column_type}"]

    default_expression = column_metadata.get("data_default")

    # Identity column (auto-generated values, implicitly NOT NULL)
    if _is_identity_column(column_metadata):
        parts.append(" GENERATED ALWAYS AS IDENTITY")
        return "".join(parts)

    # Virtual column (value computed from an expression)
    if _is_virtual_column(column_metadata):
        expression = default_expression.strip()
        parts.append(f" GENERATED ALWAYS AS ({expression}) VIRTUAL")
        return "".join(parts)

    # Regular default value
    if default_expression is not None:
        stripped = default_expression.strip()
        if stripped:
            parts.append(f" DEFAULT {stripped}")

    # NOT NULL constraint
    if column_metadata.get("nullable") == "N":
        parts.append(" NOT NULL")

    return "".join(parts)


def _generate_create_table(
    table_name: str,
    columns: list[dict],
    pk_columns: list[str] | None,
    pk_status: str | None,
    pk_name: str | None,
    unique_constraints: list[tuple[str, list[str], str]] | None,
    is_temporary: bool,
    schema_prefix: str = "",
) -> str:
    """
    Generate a complete `CREATE TABLE` statement for one table.

    The output includes column definitions, an inline PRIMARY KEY constraint
    (if any), and inline UNIQUE constraints (if any).  Foreign keys are
    emitted separately as ALTER TABLE statements by another function.

    Args:
        table_name: The table name (e.g. "CASE_REPORT").
        columns: List of column metadata dicts for this table.
        pk_columns: Ordered list of columns in the primary key, or None.
        pk_status: "ENABLED" or "DISABLED" for the PK, or None.
        pk_name: The constraint name for the PK, or None.
        unique_constraints: List of (name, [columns], status) tuples, or None.
        is_temporary: Whether this is a GLOBAL TEMPORARY TABLE.

    Returns:
        The full CREATE TABLE statement as a string.
    """
    sorted_columns = sorted(columns, key=lambda column: column.get("column_id") or 0)

    lines: list[str] = []

    prefix = "CREATE GLOBAL TEMPORARY TABLE" if is_temporary else "CREATE TABLE"
    lines.append(f"{prefix} {schema_prefix}{table_name} (")

    body_lines = [_generate_column_line(column) for column in sorted_columns]

    # Primary key constraint (inline)
    if pk_columns:
        constraint_name = pk_name or f"PK_{table_name}"
        columns_csv = ", ".join(pk_columns)
        disable_clause = " DISABLE" if pk_status == "DISABLED" else ""
        body_lines.append(f"    CONSTRAINT {constraint_name} PRIMARY KEY ({columns_csv}){disable_clause}")

    # Unique constraints (inline)
    if unique_constraints:
        for constraint_name, unique_columns, status in unique_constraints:
            columns_csv = ", ".join(unique_columns)
            disable_clause = " DISABLE" if status == "DISABLED" else ""
            body_lines.append(f"    CONSTRAINT {constraint_name} UNIQUE ({columns_csv}){disable_clause}")

    lines.append(",\n".join(body_lines))
    lines.append(");")

    return "\n".join(lines)


def _generate_foreign_key_statements(
    current_schema: str,
    fk_groups_by_table: dict[str, list[tuple[str, list[dict], str]]],
    schema_prefix: str = "",
) -> list[str]:
    """
    Generate `ALTER TABLE ... ADD FOREIGN KEY` statements for all tables.

    Foreign keys are emitted as separate ALTER TABLE statements (rather than
    inline in CREATE TABLE) so that all referenced tables can be created first.

    Cross-schema references (where the referenced table lives in a different
    schema) are schema-qualified (e.g. `REFERENCES ICSR_LOOKUP.COUNTRY`).

    Args:
        current_schema: The schema being generated. This is used to detect
            cross-schema references that need qualification.
        fk_groups_by_table: Output of `_build_foreign_key_groups()`.

    Returns:
        List of complete `ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY ...;`
        statements.
    """
    statements: list[str] = []

    for source_table in sorted(fk_groups_by_table):
        for constraint_name, column_mappings, status in fk_groups_by_table[source_table]:
            source_columns = [row["column_name"] for row in column_mappings]
            referenced_columns = [row["referenced_column"] for row in column_mappings]
            referenced_table = column_mappings[0]["referenced_table"]
            referenced_schema = column_mappings[0]["r_owner"]
            delete_rule = column_mappings[0].get("delete_rule", "NO ACTION")

            # Schema-qualify if the referenced table lives in another schema
            if referenced_schema and referenced_schema != current_schema:
                reference_target = f"{referenced_schema}.{referenced_table}"
            else:
                reference_target = f"{schema_prefix}{referenced_table}"

            source_columns_csv = ", ".join(source_columns)
            referenced_columns_csv = ", ".join(referenced_columns)

            statement = (
                f"ALTER TABLE {schema_prefix}{source_table} ADD CONSTRAINT {constraint_name}\n"
                f"    FOREIGN KEY ({source_columns_csv}) "
                f"REFERENCES {reference_target} ({referenced_columns_csv})"
            )

            if delete_rule == "CASCADE":
                statement += "\n    ON DELETE CASCADE"
            elif delete_rule == "SET NULL":
                statement += "\n    ON DELETE SET NULL"

            if status == "DISABLED":
                statement += "\n    DISABLE"

            statement += ";"
            statements.append(statement)

    return statements


def _generate_comment_statements(
    table_comments: list[dict],
    column_comments: list[dict],
    schema_prefix: str = "",
) -> list[str]:
    """
    Generate `COMMENT ON TABLE` / `COMMENT ON COLUMN` statements.

    Args:
        table_comments: List of dicts with "table_name" and "comments" keys.
        column_comments: List of dicts with "table_name", "column_name",
            and "comments" keys.

    Returns:
        List of `COMMENT ON TABLE|COLUMN ... IS '...';` statements.
    """
    statements: list[str] = []

    for table_comment in table_comments:
        comment_text = table_comment.get("comments")
        if comment_text:
            escaped_text = comment_text.replace("'", "''")
            statements.append(f"COMMENT ON TABLE {schema_prefix}{table_comment['table_name']} IS '{escaped_text}';")

    for column_comment in column_comments:
        comment_text = column_comment.get("comments")
        if comment_text:
            escaped_text = comment_text.replace("'", "''")
            statements.append(
                f"COMMENT ON COLUMN {schema_prefix}{column_comment['table_name']}.{column_comment['column_name']} "
                f"IS '{escaped_text}';"
            )

    return statements


def _section_header(title: str) -> list[str]:
    """Return a commented section header block for the DDL output."""
    separator = "-- " + "-" * 88
    return [separator, f"-- {title}", separator, ""]


def generate_schema_ddl(
    schema_name: str,
    metadata: dict[str, Any],
    schema_qualify: bool = False,
) -> str:
    """
    Generate the complete DDL script for a single database schema.

    Reads the metadata dict (tables, columns, constraints, foreign keys,
    comments) and produces a `.sql` script containing:

    1. A header comment block with generation timestamps
    2. `CREATE TABLE` statements (sorted alphabetically by table name)
    3. `ALTER TABLE ... FOREIGN KEY` statements
    4. `COMMENT ON TABLE/COLUMN` statements

    Args:
        schema_name: Name of the schema (e.g. "ICSR").
        metadata: The parsed contents of the schema's `_metadata.json` file.

    Returns:
        The full DDL script as a single string.
    """
    # Parse the export timestamp for the header
    generated_at = metadata.get("generated_at", "unknown")
    try:
        export_date = datetime.fromisoformat(generated_at).strftime("%Y-%m-%d")
    except ValueError:
        export_date = generated_at

    # Unpack metadata sections
    tables = metadata.get("tables", [])  # table-level properties
    columns = metadata.get("columns", [])  # column definitions (type, nullable, default)
    constraints = metadata.get("constraints", [])  # PK and unique constraint definitions
    constraint_columns = metadata.get("constraint_columns", [])  # which columns belong to which constraint
    foreign_keys = metadata.get("foreign_keys", [])  # FK column mappings (source -> referenced)
    table_comments = metadata.get("table_comments", [])
    column_comments = metadata.get("column_comments", [])

    # Build lookup structures
    table_info_by_name = {table["table_name"]: table for table in tables}
    columns_by_table = _group_rows_by_key(columns, "table_name")
    pk_columns_by_table, pk_status_by_table, pk_name_by_table = _build_primary_key_info(
        constraints, constraint_columns
    )
    unique_constraints_by_table = _build_unique_constraint_info(constraints, constraint_columns)
    fk_groups_by_table = _build_foreign_key_groups(foreign_keys)

    # Check for virtual columns that depend on external functions
    function_warnings = _find_required_function_warnings(columns)

    # Compute prefix for schema-qualified table names
    schema_prefix = f"{schema_name}." if schema_qualify else ""

    # Assemble the output script
    execution_order_display = " -> ".join(EXECUTION_ORDER)
    output_parts: list[str] = [
        f"-- Schema: {schema_name}",
        f"-- Generated from metadata exported on {export_date}",
        f"-- Script generated on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"-- Execution order: {execution_order_display}",
        "",
    ]

    if function_warnings:
        output_parts.append("-- WARNING: The following schema-qualified functions must")
        output_parts.append("-- exist before running this DDL:")
        for function_name in function_warnings:
            output_parts.append(f"--   {function_name}")
        output_parts.append("")

    # CREATE TABLE statements (sorted by table name).
    # Iterates columns_by_table rather than tables so that tables with no
    # columns in the metadata are silently skipped.
    for table_name in sorted(columns_by_table):
        table_columns = columns_by_table[table_name]
        table_info = table_info_by_name.get(table_name, {})
        is_temporary = table_info.get("temporary") == "Y"

        create_statement = _generate_create_table(
            table_name=table_name,
            columns=table_columns,
            pk_columns=pk_columns_by_table.get(table_name),
            pk_status=pk_status_by_table.get(table_name),
            pk_name=pk_name_by_table.get(table_name),
            unique_constraints=unique_constraints_by_table.get(table_name),
            is_temporary=is_temporary,
            schema_prefix=schema_prefix,
        )
        output_parts.append(create_statement)
        output_parts.append("")

    # Foreign key statements
    fk_statements = _generate_foreign_key_statements(schema_name, fk_groups_by_table, schema_prefix)
    if fk_statements:
        output_parts.extend(_section_header("Foreign keys"))
        for statement in fk_statements:
            output_parts.append(statement)
            output_parts.append("")

    # Comment statements (COMMENT ON TABLE / COMMENT ON COLUMN)
    comment_statements = _generate_comment_statements(table_comments, column_comments, schema_prefix)
    if comment_statements:
        output_parts.extend(_section_header("Comments"))
        for statement in comment_statements:
            output_parts.append(statement)
        output_parts.append("")

    return "\n".join(output_parts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate clean Oracle DDL from metadata JSON files.",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Directory containing schema subdirs with _metadata.json (default: {DEFAULT_INPUT_DIR.relative_to(PROJECT_ROOT)})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for generated .sql files (default: {DEFAULT_OUTPUT_DIR.relative_to(PROJECT_ROOT)})",
    )
    parser.add_argument(
        "--schemas",
        nargs="+",
        default=None,
        help="Schemas to process (default: all found in input-dir)",
    )
    parser.add_argument(
        "--schema-qualify",
        action="store_true",
        default=False,
        help="Prefix table names with the schema name (e.g. ICSR_LOOKUP.COUNTRY)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_dir: Path = args.input_dir
    output_dir: Path = args.output_dir

    if not input_dir.exists():
        print(f"Error: input directory not found: {input_dir}", file=sys.stderr)
        sys.exit(1)

    # Discover schemas, either the ones the user asked for, or all available
    if args.schemas:
        schema_dirs = [input_dir / schema for schema in args.schemas]
        missing = [directory for directory in schema_dirs if not (directory / "_metadata.json").exists()]
        if missing:
            print(
                f"Error: metadata not found for: {[d.name for d in missing]}",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        schema_dirs = sorted(
            directory
            for directory in input_dir.iterdir()
            if directory.is_dir() and (directory / "_metadata.json").exists()
        )

    if not schema_dirs:
        print("No schemas found with _metadata.json files.", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    for schema_dir in schema_dirs:
        schema_name = schema_dir.name
        metadata_path = schema_dir / "_metadata.json"

        print(f"Processing {schema_name} ...")
        with open(metadata_path, encoding="utf-8") as file:
            metadata = json.load(file)

        ddl_script = generate_schema_ddl(
            schema_name=schema_name,
            metadata=metadata,
            schema_qualify=args.schema_qualify,
        )

        output_path = output_dir / f"{schema_name}.sql"
        output_path.write_text(ddl_script, encoding="utf-8")

        # Print summary stats
        table_count = len(metadata.get("tables", []))
        fk_constraint_names = {fk["constraint_name"] for fk in metadata.get("foreign_keys", [])}
        print(f"  -> {output_path.relative_to(PROJECT_ROOT)}")
        print(f"     {table_count} tables, {len(fk_constraint_names)} FK constraints")

    print("Done!")


if __name__ == "__main__":
    main()
