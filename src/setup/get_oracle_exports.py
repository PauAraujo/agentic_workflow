import os
import json
import oracledb
import argparse

import pandas as pd

from typing import Any, Optional
from datetime import datetime, timezone

# Oracle configuration
DB_HOST =
DB_PORT =
DB_SERVICE =
DB_USER =
DB_PASSWORD =

# Target schema to export
TARGET_SCHEMA = 'ICSR_LOOKUP'
BASE_OUTPUT_DIRECTORY = '../../input/db_exports'

# Export constants
CSV_ROW_LIMIT = 1000
METADATA_FILENAME = '_metadata.json'
SEPARATOR = '-' * 40

# Oracle constants
ORACLE_COLUMN_NOT_FOUND_ERROR = 'ORA-00904'
ORACLE_SYSTEM_OWNER = 'SYS'
FOREIGN_KEY_CONSTRAINT_TYPE = 'R'
ALL_TAB_PRIVS_VIEW = 'ALL_TAB_PRIVS'
OWNER_COLUMN = 'owner'
TABLE_SCHEMA_COLUMN = 'table_schema'

def get_output_directory(schema_name: str, base_output_dir: str) -> str:
    """
    Builds the output directory path for the target schema.

    Args:
        schema_name: Name of the schema.
        base_output_dir: Base directory for exports.
    """
    schema_upper = schema_name.upper()
    return os.path.join(base_output_dir, schema_upper)

def get_connection() -> oracledb.Connection:
    """Establishes a connection to the Oracle database."""
    dsn = oracledb.makedsn(DB_HOST, DB_PORT, service_name=DB_SERVICE)
    connection = oracledb.connect(
        user=DB_USER,
        password=DB_PASSWORD,
        dsn=dsn
    )
    print("Successfully connected to the database.")
    return connection

def get_tables_in_schema(connection: oracledb.Connection, schema_name: str) -> list[str]:
    """
    Retrieves a list of table names for the given schema.

    Args:
        connection: Active Oracle database connection.
        schema_name: Name of the schema to query.
    """
    cursor = connection.cursor()
    query = """
        SELECT table_name
        FROM all_tables
        WHERE owner = :schema_name
    """
    try:
        cursor.execute(query, schema_name=schema_name.upper())
        tables = [row[0] for row in cursor.fetchall()]
        print(f"Found {len(tables)} tables in schema '{schema_name}'.")
        return tables
    finally:
        cursor.close()

def export_table_to_csv(connection: oracledb.Connection, schema_name: str, table_name: str, output_dir: str) -> None:
    """
    Exports the first N rows of a specific table to CSV.

    Args:
        connection: Active Oracle database connection.
        schema_name: Name of the schema containing the table.
        table_name: Name of the table to export.
        output_dir: Directory to save the CSV file.
    """
    query = f"""
        SELECT * FROM {schema_name}.{table_name}
        FETCH FIRST {CSV_ROW_LIMIT} ROWS ONLY
    """

    try:
        df = pd.read_sql(query, con=connection)
        filename = f"{table_name}.csv"
        file_path = os.path.join(output_dir, filename)
        df.to_csv(file_path, index=False)
        print(f"Exported {len(df)} rows from {table_name} to {filename}")
    except (oracledb.DatabaseError, pd.errors.DatabaseError) as e:
        print(f"Skipped {table_name}: {e}")
    except TypeError as e:
        print(f"Skipped {table_name}: Cannot convert data to CSV (likely contains binary/BLOB data): {e}")

def fetch_rows(connection: oracledb.Connection, query: str, params: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """
    Executes a query and returns rows as a list of dicts.

    Args:
        connection: Active Oracle database connection.
        query: SQL query to execute.
        params: Optional dictionary of query parameters.
    """
    cursor = connection.cursor()
    try:
        cursor.execute(query, params or {})
        columns = [col[0].lower() for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        cursor.close()

def json_default(value: Any) -> str:
    """JSON serializer for objects not serializable by default json code."""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            pass
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    return str(value)

def fetch_rows_with_optional_columns(
    connection: oracledb.Connection,
    select_from_where: str,
    base_cols: list[str],
    optional_cols: list[str],
    params: Optional[dict[str, Any]] = None
) -> list[dict[str, Any]]:
    """
    Executes a query with optional columns, retrying if columns are unsupported.

    Args:
        connection: Active Oracle database connection.
        select_from_where: SQL fragment starting with FROM and including WHERE clause.
        base_cols: List of mandatory column names.
        optional_cols: List of optional column names.
        params: Optional dictionary of query parameters.
    """
    remaining_optional = list(optional_cols)
    select_cols = base_cols + remaining_optional
    while True:
        query = f"SELECT {', '.join(select_cols)} {select_from_where}"
        try:
            return fetch_rows(connection, query, params=params)
        except oracledb.DatabaseError as exc:
            error_message = str(exc)
            if ORACLE_COLUMN_NOT_FOUND_ERROR not in error_message or '"' not in error_message:
                raise
            missing = error_message.split('"')[1].lower()
            if missing in remaining_optional:
                remaining_optional.remove(missing)
                select_cols = base_cols + remaining_optional
                continue
            raise

def get_view_columns(connection: oracledb.Connection, view_name: str, owner: str = ORACLE_SYSTEM_OWNER) -> set[str]:
    """
    Returns a set of lowercased column names for a data dictionary view.

    Args:
        connection: Active Oracle database connection.
        view_name: Name of the data dictionary view.
        owner: Owner of the view (default is ORACLE_SYSTEM_OWNER).
    """
    rows = fetch_rows(
        connection,
        """
        SELECT column_name
        FROM all_tab_columns
        WHERE owner = :owner AND table_name = :view_name
        """,
        {"owner": owner, "view_name": view_name.upper()},
    )
    return {row["column_name"].lower() for row in rows}

def export_schema_metadata(connection: oracledb.Connection, schema_name: str, output_dir: str) -> None:
    """
    Exports schema metadata to a JSON file.

    Args:
        connection: Active Oracle database connection.
        schema_name: Name of the schema to export metadata for.
        output_dir: Directory to save the metadata JSON file.
    """
    schema_upper = schema_name.upper()
    schema_params = {"schema_name": schema_upper}

    metadata = {
        "schema": schema_upper,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tables": fetch_rows(
            connection,
            """
            SELECT owner, table_name, tablespace_name, temporary, partitioned,
                   compression, logging, num_rows, last_analyzed
            FROM all_tables
            WHERE owner = :schema_name
            """,
            schema_params,
        ),
        "table_comments": fetch_rows(
            connection,
            """
            SELECT owner, table_name, comments
            FROM all_tab_comments
            WHERE owner = :schema_name
            """,
            schema_params,
        ),
        "columns": fetch_rows_with_optional_columns(
            connection,
            "FROM all_tab_columns WHERE owner = :schema_name",
            base_cols=[
                "owner",
                "table_name",
                "column_name",
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
            optional_cols=[
                "virtual_column",
                "identity_column",
            ],
            params=schema_params,
        ),
        "column_comments": fetch_rows(
            connection,
            """
            SELECT owner, table_name, column_name, comments
            FROM all_col_comments
            WHERE owner = :schema_name
            """,
            schema_params,
        ),
        "constraints": fetch_rows(
            connection,
            """
            SELECT owner, constraint_name, constraint_type, table_name,
                   search_condition, r_owner, r_constraint_name, delete_rule,
                   deferrable, deferred, status
            FROM all_constraints
            WHERE owner = :schema_name
            """,
            schema_params,
        ),
        "constraint_columns": fetch_rows(
            connection,
            """
            SELECT owner, constraint_name, table_name, column_name, position
            FROM all_cons_columns
            WHERE owner = :schema_name
            """,
            schema_params,
        ),
        "foreign_keys": fetch_rows(
            connection,
            f"""
            SELECT c.owner, c.table_name, c.constraint_name,
                   c.r_owner, rc.table_name AS referenced_table,
                   c.delete_rule, c.deferrable, c.deferred, c.status,
                   cc.column_name, cc.position,
                   rcc.column_name AS referenced_column
            FROM all_constraints c
            JOIN all_cons_columns cc
              ON c.owner = cc.owner
             AND c.constraint_name = cc.constraint_name
             AND c.table_name = cc.table_name
            JOIN all_constraints rc
              ON c.r_owner = rc.owner
             AND c.r_constraint_name = rc.constraint_name
            JOIN all_cons_columns rcc
              ON rc.owner = rcc.owner
             AND rc.constraint_name = rcc.constraint_name
             AND rc.table_name = rcc.table_name
             AND cc.position = rcc.position
            WHERE c.constraint_type = '{FOREIGN_KEY_CONSTRAINT_TYPE}'
              AND c.owner = :schema_name
            ORDER BY c.table_name, c.constraint_name, cc.position
            """,
            schema_params,
        ),
        "indexes": fetch_rows(
            connection,
            """
            SELECT owner, index_name, table_name, uniqueness, index_type,
                   tablespace_name, compression, status
            FROM all_indexes
            WHERE owner = :schema_name
            """,
            schema_params,
        ),
        "index_columns": fetch_rows(
            connection,
            """
            SELECT index_owner, index_name, table_name, column_name,
                   column_position, descend
            FROM all_ind_columns
            WHERE index_owner = :schema_name
            """,
            schema_params,
        ),
        "triggers": fetch_rows(
            connection,
            """
            SELECT owner, trigger_name, table_name, triggering_event,
                   trigger_type, status, when_clause, description
            FROM all_triggers
            WHERE owner = :schema_name
            """,
            schema_params,
        ),
        "grants": None,
        "synonyms": fetch_rows(
            connection,
            """
            SELECT owner, synonym_name, table_owner, table_name, db_link
            FROM all_synonyms
            WHERE table_owner = :schema_name
            """,
            schema_params,
        ),
    }

    grants_columns = get_view_columns(connection, ALL_TAB_PRIVS_VIEW)
    owner_col = OWNER_COLUMN if OWNER_COLUMN in grants_columns else TABLE_SCHEMA_COLUMN
    if owner_col in grants_columns:
        grants_select_cols = [
            owner_col,
            "table_name",
            "grantee",
            "privilege",
            "grantable",
        ]
        if "type" in grants_columns:
            grants_select_cols.append("type")
        elif "hierarchy" in grants_columns:
            grants_select_cols.append("hierarchy")
        grants_query = (
            f"SELECT {', '.join(grants_select_cols)} "
            f"FROM all_tab_privs WHERE {owner_col} = :schema_name"
        )
        metadata["grants"] = fetch_rows(
            connection,
            grants_query,
            schema_params,
        )
    else:
        metadata["grants"] = []

    metadata_path = os.path.join(output_dir, METADATA_FILENAME)
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, default=json_default)
    print(f"Wrote metadata to {metadata_path}")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Oracle schema data and metadata.")
    parser.add_argument(
        "--export-data",
        action="store_true",
        help="Export table data to CSV (first 1000 rows).",
    )
    parser.add_argument(
        "--export-metadata",
        action="store_true",
        help="Export schema metadata to JSON.",
    )
    return parser.parse_args()

def run_exports() -> None:
    args = parse_args()
    export_data = args.export_data or args.export_metadata
    export_metadata = args.export_metadata or args.export_data
    if not export_data and not export_metadata:
        export_data = export_metadata = True

    output_directory = get_output_directory(TARGET_SCHEMA, BASE_OUTPUT_DIRECTORY)
    os.makedirs(output_directory, exist_ok=True)

    conn = get_connection()
    tables = get_tables_in_schema(conn, TARGET_SCHEMA)

    print(f"Starting export for schema: {TARGET_SCHEMA}...")
    print(SEPARATOR)

    if export_data:
        for table in tables:
            export_table_to_csv(conn, TARGET_SCHEMA, table, output_directory)

    if export_metadata:
        export_schema_metadata(conn, TARGET_SCHEMA, output_directory)

    conn.close()
    print(SEPARATOR)
    print("Export process completed.")

if __name__ == "__main__":
    run_exports()
