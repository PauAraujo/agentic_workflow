import csv
import json
import oracledb
import argparse

from pathlib import Path
from typing import Any
from datetime import datetime, timezone

from sql_query_assistant.config import DatabaseSettings

project_root = Path(__file__).resolve().parents[1]

# Defaults
DEFAULT_SCHEMA = "ICSR_EMA"
BASE_OUTPUT_DIRECTORY = project_root / "input" / "db_exports"
CSV_ROW_LIMIT = 1000
METADATA_FILENAME = "_metadata.json"
SEPARATOR = "-" * 40

# Oracle constants
ORACLE_COLUMN_NOT_FOUND_ERROR = "ORA-00904"  # raised when a SELECT references a non-existent column
FOREIGN_KEY_CONSTRAINT_TYPE = "R"  # Oracle constraint_type value for foreign keys
# SQL fragment appended to WHERE clauses to exclude Oracle internal/system tables
SYSTEM_TABLE_FILTERS = """
    AND {table_col} NOT LIKE 'DR$%'
    AND {table_col} NOT LIKE 'BIN$%'
    AND {table_col} NOT LIKE 'MLOG$%'
    AND {table_col} NOT LIKE 'RUPD$%'
    AND {table_col} NOT LIKE 'ZZ\\_%' ESCAPE '\\'
    AND {table_col} NOT LIKE 'RV$%'
"""

# Oracle data dictionary view and column name constants
# Used to build queries against Oracle's metadata catalog
ALL_TABLES_VIEW = "all_tables"  # table-level info (row counts, tablespace, etc.)
ALL_TAB_COMMENTS_VIEW = "all_tab_comments"  # table-level comments
ALL_TAB_COLUMNS_VIEW = "all_tab_columns"  # column definitions (type, length, nullable)
ALL_COL_COMMENTS_VIEW = "all_col_comments"  # column-level comments
ALL_CONSTRAINTS_VIEW = "all_constraints"  # PKs, FKs, unique, check constraints
ALL_CONS_COLUMNS_VIEW = "all_cons_columns"  # which columns belong to each constraint
ALL_INDEXES_VIEW = "all_indexes"  # index definitions
ALL_IND_COLUMNS_VIEW = "all_ind_columns"  # which columns belong to each index
ALL_TRIGGERS_VIEW = "all_triggers"  # trigger definitions
ALL_SYNONYMS_VIEW = "all_synonyms"  # synonym aliases for tables/views

# Column names shared across multiple dictionary views (used in SELECT and WHERE clauses)
OWNER_COL = "owner"
TABLE_NAME_COL = "table_name"
COLUMN_NAME_COL = "column_name"
CONSTRAINT_NAME_COL = "constraint_name"

# Bind-variable names used in parameterised queries
PARAM_SCHEMA_NAME = "schema_name"


def get_connection() -> oracledb.Connection:
    """
    Connect to Oracle using credentials from DatabaseSettings (loaded from .env).

    Requires DB_TYPE=oracle in .env so that DatabaseSettings validates
    all Oracle credentials (DB_HOST, DB_SERVICE, DB_USER, DB_PASSWORD).
    """
    db = DatabaseSettings()
    dsn = oracledb.makedsn(
        db.oracle_host,
        db.oracle_port,
        service_name=db.oracle_service
    )
    connection = oracledb.connect(
        user=db.oracle_user,
        password=db.oracle_password,
        dsn=dsn
    )
    print("Successfully connected to the database.")
    return connection


def fetch_rows(
        connection: oracledb.Connection,
        sql_query: str,
        params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """
    Execute a query and return every row as a dict mapping column names to values.

    Args:
        connection: Active database connection
        sql_query: SQL query to execute
        params: Optional dict of bind variables for parameterised queries

    Returns:
        List of rows, where each row is a dict mapping column names to values
    """

    cursor = connection.cursor()
    try:
        cursor.execute(sql_query, params or {})
        col_names = [desc[0].lower() for desc in cursor.description]
        rows = [dict(zip(col_names, row)) for row in cursor.fetchall()]
    finally:
        cursor.close()
    return rows


def fetch_rows_with_optional_columns(
    connection: oracledb.Connection,
    from_where_clause: str,
    base_cols: list[str],
    optional_cols: list[str],
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Execute a query with graceful degradation for optional columns.

    Tries to SELECT base_cols + optional_cols. base_cols MUST exist (errors
    are raised). optional_cols MAY not exist on older Oracle versions.
    If Oracle reports one is missing (ORA-00904), it is silently dropped
    and the query retried.

    Args:
        connection: Active database connection
        from_where_clause: SQL fragment containing FROM and WHERE clauses (without SELECT)
        base_cols: List of column names that must be selected (lowercase)
        optional_cols: List of column names that are nice-to-have but may not exist on all Oracle versions (lowercase)
        params: Optional dict of bind variables for parameterised queries

    Returns:
        List of rows, where each row is a dict mapping column names to values.
        Columns from optional_cols that were dropped due to missing-column errors will simply be absent from the dicts.
    """
    remaining_optional = optional_cols.copy() # copy so .remove() below doesn't modify the original
    cols_to_select = base_cols + remaining_optional
    while True:
        query = f"SELECT {', '.join(cols_to_select)} {from_where_clause}"
        try:
            return fetch_rows(connection, query, params=params)
        except oracledb.DatabaseError as exc:
            # Oracle errors look like: ORA-00904: invalid identifier "VIRTUAL_COLUMN"
            # we only handle missing-column errors for optional columns; everything else is re-raised
            error_message = str(exc)
            # check if Oracle reported an invalid identifier (ORA-00904)
            is_column_not_found = ORACLE_COLUMN_NOT_FOUND_ERROR in error_message
            # check that quotes exist before attempting to parse
            can_parse_column_name = '"' in error_message
            # If it's not a missing column error, or if we can't parse the missing column name
            if not is_column_not_found or not can_parse_column_name:
                raise #  re-raise the unexpected error, instead of silently dropping columns

            # We know a column is missing, but which column?
            missing = error_message.split('"')[1].lower()
            if missing not in remaining_optional:
                raise  # a required column is missing, that's a real error

            # We only silently drop columns explicitly marked as optional
            remaining_optional.remove(missing)
            cols_to_select = base_cols + remaining_optional
            continue


def json_default(value: Any) -> str:
    """
    Fallback serialiser for json.dump. Converts Oracle types
    (datetime, RAW/BLOB bytes, LOB handles) to JSON-safe strings
    """
    # Handle datetime and date types with isoformat
    if hasattr(value, "isoformat"):
        return value.isoformat()
    # Handle RAW/BLOB types returned as bytes or bytearray by oracledb
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    return str(value)


def get_table_names_in_schema(
    connection: oracledb.Connection, schema_name: str
) -> list[str]:
    """
    List all user tables in a schema, excluding Oracle internal/system tables.

    Args:
        connection: Active database connection
        schema_name: Name of the schema to list tables from

    Returns:
        List of table names in the specified schema
    """
    filters = SYSTEM_TABLE_FILTERS.format(table_col=TABLE_NAME_COL)
    query = f"""
        SELECT {TABLE_NAME_COL}
        FROM {ALL_TABLES_VIEW}
        WHERE {OWNER_COL} = :{PARAM_SCHEMA_NAME}
        {filters}
    """
    rows = fetch_rows(
        connection,
        query,
        params={PARAM_SCHEMA_NAME: schema_name.upper()}
    )
    print(
        f"Found {len(rows)} tables in schema '{schema_name}' (excluding Oracle system tables)."
    )
    return [row[TABLE_NAME_COL] for row in rows]


def export_table_to_csv(
    connection: oracledb.Connection,
    schema_name: str,
    table_name: str,
    output_dir: Path
) -> None:
    """
    Export a sample of rows from an Oracle table to a CSV file.

    Queries up to CSV_ROW_LIMIT rows from {schema_name}.{table_name} and writes
    them to {output_dir}/{table_name}.csv. Tables that can't be exported
    (e.g. binary/BLOB data, encoding issues, permission errors) are skipped
    with a warning.

    Args:
        connection: Active database connection
        schema_name: Name of the schema containing the table
        table_name: Name of the table to export
        output_dir: Directory to write the CSV file to
    """
    query = f"""
        SELECT * FROM {schema_name}.{table_name}
        FETCH FIRST {CSV_ROW_LIMIT} ROWS ONLY
    """

    try:
        rows = fetch_rows(connection, query)
        if not rows:
            print(f"Skipped {table_name}: no rows returned")
            return

        file_path = output_dir / f"{table_name}.csv"
        fieldnames = list(rows[0].keys()) # column names
        with file_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader() # write first line (column names)
            writer.writerows(rows) # write the data rows
        print(f"Exported {len(rows)} rows from {table_name} to {file_path.name}")
    except oracledb.DatabaseError as e:
        print(f"Skipped {table_name}: {e}")


def export_schema_metadata_to_json(
        connection: oracledb.Connection,
        schema_name: str,
        output_dir: Path
) -> None:
    """
    Query Oracle's data dictionary and write a single JSON file containing
    the full schema structure: tables, columns, comments, constraints,
    foreign keys, indexes, triggers, and synonyms.

    This JSON is later consumed by the table card generator,
    to create table cards with rich metadata for the LLM.

    Args:
        connection: Active database connection
        schema_name: Name of the schema to export metadata for
        output_dir: Directory to write the JSON file to
    """
    schema_upper = schema_name.upper()
    schema_params = {PARAM_SCHEMA_NAME: schema_upper}
    table_filters = SYSTEM_TABLE_FILTERS.format(table_col=TABLE_NAME_COL)

    metadata = {
        "schema": schema_upper,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tables": fetch_rows(
            connection,
            f"""
            SELECT {OWNER_COL}, {TABLE_NAME_COL}, tablespace_name, temporary, partitioned,
                   compression, logging, num_rows, last_analyzed
            FROM {ALL_TABLES_VIEW}
            WHERE {OWNER_COL} = :{PARAM_SCHEMA_NAME}
            {table_filters}
            """,
            schema_params,
        ),
        "table_comments": fetch_rows(
            connection,
            f"""
            SELECT {OWNER_COL}, {TABLE_NAME_COL}, comments
            FROM {ALL_TAB_COMMENTS_VIEW}
            WHERE {OWNER_COL} = :{PARAM_SCHEMA_NAME}
            {table_filters}
            """,
            schema_params,
        ),
        "columns": fetch_rows_with_optional_columns(
            connection,
            f"FROM {ALL_TAB_COLUMNS_VIEW} WHERE {OWNER_COL} = :{PARAM_SCHEMA_NAME} {table_filters}",
            base_cols=[
                OWNER_COL,
                TABLE_NAME_COL,
                COLUMN_NAME_COL,
                "column_id",
                "data_type",
                "data_length",
                "data_precision",
                "data_scale",
                "nullable",
                "data_default",
                "char_length",
                "char_used",
                "char_col_decl_length",
            ],
            optional_cols=[  # not present on all Oracle versions; useful for DDL generation
                "virtual_column",
                "identity_column",
            ],
            params=schema_params,
        ),
        "column_comments": fetch_rows(
            connection,
            f"""
            SELECT {OWNER_COL}, {TABLE_NAME_COL}, {COLUMN_NAME_COL}, comments
            FROM {ALL_COL_COMMENTS_VIEW}
            WHERE {OWNER_COL} = :{PARAM_SCHEMA_NAME}
            {table_filters}
            """,
            schema_params,
        ),
        "constraints": fetch_rows(
            connection,
            f"""
            SELECT {OWNER_COL}, {CONSTRAINT_NAME_COL}, constraint_type, {TABLE_NAME_COL},
                   search_condition, r_owner, r_constraint_name, delete_rule,
                   deferrable, deferred, status
            FROM {ALL_CONSTRAINTS_VIEW}
            WHERE {OWNER_COL} = :{PARAM_SCHEMA_NAME}
            {table_filters}
            """,
            schema_params,
        ),
        "constraint_columns": fetch_rows(
            connection,
            f"""
            SELECT {OWNER_COL}, {CONSTRAINT_NAME_COL}, {TABLE_NAME_COL}, {COLUMN_NAME_COL}, position
            FROM {ALL_CONS_COLUMNS_VIEW}
            WHERE {OWNER_COL} = :{PARAM_SCHEMA_NAME}
            {table_filters}
            """,
            schema_params,
        ),
        # Foreign keys require a 4-way join to resolve:
        #   c   = FK constraint (type 'R')
        #   cc  = columns of the FK constraint
        #   rc  = the referenced (parent) constraint (PK/UK)
        #   rcc = columns of the referenced constraint
        # The cc.position = rcc.position join aligns composite FK columns correctly.
        "foreign_keys": fetch_rows(
            connection,
            f"""
            SELECT c.{OWNER_COL}, c.{TABLE_NAME_COL}, c.{CONSTRAINT_NAME_COL}, 
                   c.r_owner, rc.{TABLE_NAME_COL} AS referenced_table,
                   c.delete_rule, c.deferrable, c.deferred, c.status,
                   cc.{COLUMN_NAME_COL}, cc.position,
                   rcc.{COLUMN_NAME_COL} AS referenced_column
            FROM {ALL_CONSTRAINTS_VIEW} c
            JOIN {ALL_CONS_COLUMNS_VIEW} cc
              ON c.{OWNER_COL} = cc.{OWNER_COL}
             AND c.{CONSTRAINT_NAME_COL} = cc.{CONSTRAINT_NAME_COL}
             AND c.{TABLE_NAME_COL} = cc.{TABLE_NAME_COL}
            JOIN {ALL_CONSTRAINTS_VIEW} rc
              ON c.r_owner = rc.{OWNER_COL}
             AND c.r_constraint_name = rc.{CONSTRAINT_NAME_COL}
            JOIN {ALL_CONS_COLUMNS_VIEW} rcc
              ON rc.{OWNER_COL} = rcc.{OWNER_COL}
             AND rc.{CONSTRAINT_NAME_COL} = rcc.{CONSTRAINT_NAME_COL}
             AND rc.{TABLE_NAME_COL} = rcc.{TABLE_NAME_COL}
             AND cc.position = rcc.position
            WHERE c.constraint_type = '{FOREIGN_KEY_CONSTRAINT_TYPE}'
              AND c.{OWNER_COL} = :{PARAM_SCHEMA_NAME}
              {SYSTEM_TABLE_FILTERS.format(table_col=f'c.{TABLE_NAME_COL}')}
            ORDER BY c.{TABLE_NAME_COL}, c.{CONSTRAINT_NAME_COL}, cc.position
            """,
            schema_params,
        ),
        "indexes": fetch_rows(
            connection,
            f"""
            SELECT {OWNER_COL}, index_name, {TABLE_NAME_COL}, uniqueness, index_type,
                   tablespace_name, compression, status
            FROM {ALL_INDEXES_VIEW}
            WHERE {OWNER_COL} = :{PARAM_SCHEMA_NAME}
            {table_filters}
            """,
            schema_params,
        ),
        "index_columns": fetch_rows(
            connection,
            f"""
            SELECT index_owner, index_name, {TABLE_NAME_COL}, {COLUMN_NAME_COL},
                   column_position, descend
            FROM {ALL_IND_COLUMNS_VIEW}
            WHERE index_owner = :{PARAM_SCHEMA_NAME}
            {table_filters}
            """,
            schema_params,
        ),
        "triggers": fetch_rows(
            connection,
            f"""
            SELECT {OWNER_COL}, trigger_name, {TABLE_NAME_COL}, triggering_event,
                   trigger_type, status, when_clause, description
            FROM {ALL_TRIGGERS_VIEW}
            WHERE {OWNER_COL} = :{PARAM_SCHEMA_NAME}
            {table_filters}
            """,
            schema_params,
        ),
        "synonyms": fetch_rows(
            connection,
            f"""
            SELECT {OWNER_COL}, synonym_name, table_owner, {TABLE_NAME_COL}, db_link
            FROM {ALL_SYNONYMS_VIEW}
            WHERE table_owner = :{PARAM_SCHEMA_NAME}
            {table_filters}
            """,
            schema_params,
        ),
    }

    metadata_path = output_dir / METADATA_FILENAME
    with metadata_path.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, default=json_default)
    print(f"Wrote metadata to {metadata_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export Oracle schema data and metadata."
    )
    parser.add_argument(
        "--export-csv",
        action="store_true",
        help="Export sample table data to CSV (first 1000 rows).",
    )
    parser.add_argument(
        "--export-schema-metadata",
        action="store_true",
        help="Export schema metadata (columns, constraints, FKs, indexes) to JSON.",
    )
    parser.add_argument(
        "--target-schema",
        default=DEFAULT_SCHEMA,
        help=f"Target schema to export (default: {DEFAULT_SCHEMA}).",
    )
    return parser.parse_args()


def run_exports() -> None:
    args = parse_args()
    # If neither flag is given, export both
    run_both = not args.export_csv and not args.export_schema_metadata

    schema = args.target_schema
    output_directory = BASE_OUTPUT_DIRECTORY / schema.upper()
    output_directory.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    try:
        tables = get_table_names_in_schema(conn, schema)
        print(f"Starting export for schema: {schema}...")
        print(SEPARATOR)

        if args.export_csv or run_both:
            for table in tables:
                export_table_to_csv(conn, schema, table, output_directory)

        if args.export_schema_metadata or run_both:
            export_schema_metadata_to_json(conn, schema, output_directory)
    finally:
        conn.close()

    print(SEPARATOR)
    print("Export process completed.")


if __name__ == "__main__":
    run_exports()
