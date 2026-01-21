import os
import json
import oracledb
import argparse

import pandas as pd

from pathlib import Path
from dotenv import load_dotenv
from typing import Any, Optional
from datetime import datetime, timezone

# Load environment variables from project root .env
# override=True ensures .env values take precedence over system env vars
project_root = Path(__file__).resolve().parents[1]
load_dotenv(project_root / ".env", override=True)

# Oracle configuration
DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "1521"))
DB_SERVICE = os.getenv("DB_SERVICE")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# Validate required DB credentials are set
if not all([DB_HOST, DB_SERVICE, DB_USER, DB_PASSWORD]):
    raise ValueError(
        "Missing required database credentials in .env file. "
        "Please set DB_HOST, DB_PORT, DB_SERVICE, DB_USER, and DB_PASSWORD"
    )

# Target schema to export
TARGET_SCHEMA = 'ICSR_EMA'
BASE_OUTPUT_DIRECTORY = '../input/db_exports'

# Export constants
CSV_ROW_LIMIT = 1000
METADATA_FILENAME = '_metadata.json'
SEPARATOR = '-' * 40

# Oracle constants
ORACLE_COLUMN_NOT_FOUND_ERROR = 'ORA-00904'
ORACLE_SYSTEM_OWNER = 'SYS'
FOREIGN_KEY_CONSTRAINT_TYPE = 'R'

# System table exclusion filters
SYSTEM_TABLE_FILTERS = """
    AND {table_col} NOT LIKE 'DR$%'
    AND {table_col} NOT LIKE 'BIN$%'
    AND {table_col} NOT LIKE 'MLOG$%'
    AND {table_col} NOT LIKE 'RUPD$%'
    AND {table_col} NOT LIKE 'ZZ_%'
    AND {table_col} NOT LIKE 'RV$%'
"""

# Oracle data dictionary view names
ALL_TABLES_VIEW = 'all_tables'
ALL_TAB_COMMENTS_VIEW = 'all_tab_comments'
ALL_TAB_COLUMNS_VIEW = 'all_tab_columns'
ALL_COL_COMMENTS_VIEW = 'all_col_comments'
ALL_CONSTRAINTS_VIEW = 'all_constraints'
ALL_CONS_COLUMNS_VIEW = 'all_cons_columns'
ALL_INDEXES_VIEW = 'all_indexes'
ALL_IND_COLUMNS_VIEW = 'all_ind_columns'
ALL_TRIGGERS_VIEW = 'all_triggers'
ALL_SYNONYMS_VIEW = 'all_synonyms'
ALL_TAB_PRIVS_VIEW = 'all_tab_privs'

# Common column names
COL_OWNER = 'owner'
COL_TABLE_NAME = 'table_name'
COL_COLUMN_NAME = 'column_name'
COL_CONSTRAINT_NAME = 'constraint_name'

# Parameter names
PARAM_SCHEMA_NAME = 'schema_name'
PARAM_OWNER = 'owner'
PARAM_VIEW_NAME = 'view_name'

# Grant-related column names
COL_GRANTEE = 'grantee'
COL_PRIVILEGE = 'privilege'
COL_GRANTABLE = 'grantable'
COL_TYPE = 'type'
COL_HIERARCHY = 'hierarchy'

# Legacy column name (for compatibility)
OWNER_COLUMN = COL_OWNER
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
    Retrieves a list of table names for the given schema, excluding Oracle system tables.

    Args:
        connection: Active Oracle database connection.
        schema_name: Name of the schema to query.
    """
    cursor = connection.cursor()
    filters = SYSTEM_TABLE_FILTERS.format(table_col=COL_TABLE_NAME)
    query = f"""
        SELECT {COL_TABLE_NAME}
        FROM {ALL_TABLES_VIEW}
        WHERE {COL_OWNER} = :{PARAM_SCHEMA_NAME}
        {filters}
    """
    try:
        cursor.execute(query, **{PARAM_SCHEMA_NAME: schema_name.upper()})
        tables = [row[0] for row in cursor.fetchall()]
        print(f"Found {len(tables)} tables in schema '{schema_name}' (excluding Oracle system tables).")
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

    cursor = connection.cursor()
    try:
        cursor.execute(query)
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()

        # Convert to DataFrame
        df = pd.DataFrame(rows, columns=columns)

        filename = f"{table_name}.csv"
        file_path = os.path.join(output_dir, filename)
        df.to_csv(file_path, index=False)
        print(f"Exported {len(df)} rows from {table_name} to {filename}")
    except oracledb.DatabaseError as e:
        print(f"Skipped {table_name}: {e}")
    except TypeError as e:
        print(f"Skipped {table_name}: Cannot convert data to CSV (likely contains binary/BLOB data): {e}")
    except UnicodeDecodeError as e:
        print(f"Skipped {table_name}: Unicode decoding error (likely contains non-UTF-8 data): {e}")
    finally:
        cursor.close()

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
        f"""
        SELECT {COL_COLUMN_NAME}
        FROM {ALL_TAB_COLUMNS_VIEW}
        WHERE {COL_OWNER} = :{PARAM_OWNER} AND {COL_TABLE_NAME} = :{PARAM_VIEW_NAME}
        """,
        {PARAM_OWNER: owner, PARAM_VIEW_NAME: view_name.upper()},
    )
    return {row[COL_COLUMN_NAME].lower() for row in rows}

def export_schema_metadata(connection: oracledb.Connection, schema_name: str, output_dir: str) -> None:
    """
    Exports schema metadata to a JSON file.

    Args:
        connection: Active Oracle database connection.
        schema_name: Name of the schema to export metadata for.
        output_dir: Directory to save the metadata JSON file.
    """
    schema_upper = schema_name.upper()
    schema_params = {PARAM_SCHEMA_NAME: schema_upper}

    # Apply system table filters
    table_filters = SYSTEM_TABLE_FILTERS.format(table_col=COL_TABLE_NAME)

    metadata = {
        "schema": schema_upper,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tables": fetch_rows(
            connection,
            f"""
            SELECT {COL_OWNER}, {COL_TABLE_NAME}, tablespace_name, temporary, partitioned,
                   compression, logging, num_rows, last_analyzed
            FROM {ALL_TABLES_VIEW}
            WHERE {COL_OWNER} = :{PARAM_SCHEMA_NAME}
            {table_filters}
            """,
            schema_params,
        ),
        "table_comments": fetch_rows(
            connection,
            f"""
            SELECT {COL_OWNER}, {COL_TABLE_NAME}, comments
            FROM {ALL_TAB_COMMENTS_VIEW}
            WHERE {COL_OWNER} = :{PARAM_SCHEMA_NAME}
            {table_filters}
            """,
            schema_params,
        ),
        "columns": fetch_rows_with_optional_columns(
            connection,
            f"FROM {ALL_TAB_COLUMNS_VIEW} WHERE {COL_OWNER} = :{PARAM_SCHEMA_NAME} {table_filters}",
            base_cols=[
                COL_OWNER,
                COL_TABLE_NAME,
                COL_COLUMN_NAME,
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
            f"""
            SELECT {COL_OWNER}, {COL_TABLE_NAME}, {COL_COLUMN_NAME}, comments
            FROM {ALL_COL_COMMENTS_VIEW}
            WHERE {COL_OWNER} = :{PARAM_SCHEMA_NAME}
            {table_filters}
            """,
            schema_params,
        ),
        "constraints": fetch_rows(
            connection,
            f"""
            SELECT {COL_OWNER}, {COL_CONSTRAINT_NAME}, constraint_type, {COL_TABLE_NAME},
                   search_condition, r_owner, r_constraint_name, delete_rule,
                   deferrable, deferred, status
            FROM {ALL_CONSTRAINTS_VIEW}
            WHERE {COL_OWNER} = :{PARAM_SCHEMA_NAME}
            {table_filters}
            """,
            schema_params,
        ),
        "constraint_columns": fetch_rows(
            connection,
            f"""
            SELECT {COL_OWNER}, {COL_CONSTRAINT_NAME}, {COL_TABLE_NAME}, {COL_COLUMN_NAME}, position
            FROM {ALL_CONS_COLUMNS_VIEW}
            WHERE {COL_OWNER} = :{PARAM_SCHEMA_NAME}
            {table_filters}
            """,
            schema_params,
        ),
        "foreign_keys": fetch_rows(
            connection,
            f"""
            SELECT c.{COL_OWNER}, c.{COL_TABLE_NAME}, c.{COL_CONSTRAINT_NAME},
                   c.r_owner, rc.{COL_TABLE_NAME} AS referenced_table,
                   c.delete_rule, c.deferrable, c.deferred, c.status,
                   cc.{COL_COLUMN_NAME}, cc.position,
                   rcc.{COL_COLUMN_NAME} AS referenced_column
            FROM {ALL_CONSTRAINTS_VIEW} c
            JOIN {ALL_CONS_COLUMNS_VIEW} cc
              ON c.{COL_OWNER} = cc.{COL_OWNER}
             AND c.{COL_CONSTRAINT_NAME} = cc.{COL_CONSTRAINT_NAME}
             AND c.{COL_TABLE_NAME} = cc.{COL_TABLE_NAME}
            JOIN {ALL_CONSTRAINTS_VIEW} rc
              ON c.r_owner = rc.{COL_OWNER}
             AND c.r_constraint_name = rc.{COL_CONSTRAINT_NAME}
            JOIN {ALL_CONS_COLUMNS_VIEW} rcc
              ON rc.{COL_OWNER} = rcc.{COL_OWNER}
             AND rc.{COL_CONSTRAINT_NAME} = rcc.{COL_CONSTRAINT_NAME}
             AND rc.{COL_TABLE_NAME} = rcc.{COL_TABLE_NAME}
             AND cc.position = rcc.position
            WHERE c.constraint_type = '{FOREIGN_KEY_CONSTRAINT_TYPE}'
              AND c.{COL_OWNER} = :{PARAM_SCHEMA_NAME}
              {SYSTEM_TABLE_FILTERS.format(table_col=f'c.{COL_TABLE_NAME}')}
            ORDER BY c.{COL_TABLE_NAME}, c.{COL_CONSTRAINT_NAME}, cc.position
            """,
            schema_params,
        ),
        "indexes": fetch_rows(
            connection,
            f"""
            SELECT {COL_OWNER}, index_name, {COL_TABLE_NAME}, uniqueness, index_type,
                   tablespace_name, compression, status
            FROM {ALL_INDEXES_VIEW}
            WHERE {COL_OWNER} = :{PARAM_SCHEMA_NAME}
            {table_filters}
            """,
            schema_params,
        ),
        "index_columns": fetch_rows(
            connection,
            f"""
            SELECT index_owner, index_name, {COL_TABLE_NAME}, {COL_COLUMN_NAME},
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
            SELECT {COL_OWNER}, trigger_name, {COL_TABLE_NAME}, triggering_event,
                   trigger_type, status, when_clause, description
            FROM {ALL_TRIGGERS_VIEW}
            WHERE {COL_OWNER} = :{PARAM_SCHEMA_NAME}
            {table_filters}
            """,
            schema_params,
        ),
        "grants": None,
        "synonyms": fetch_rows(
            connection,
            f"""
            SELECT {COL_OWNER}, synonym_name, table_owner, {COL_TABLE_NAME}, db_link
            FROM {ALL_SYNONYMS_VIEW}
            WHERE table_owner = :{PARAM_SCHEMA_NAME}
            {table_filters}
            """,
            schema_params,
        ),
    }

    grants_columns = get_view_columns(connection, ALL_TAB_PRIVS_VIEW)
    owner_col = OWNER_COLUMN if OWNER_COLUMN in grants_columns else TABLE_SCHEMA_COLUMN
    if owner_col in grants_columns:
        grants_select_cols = [
            owner_col,
            COL_TABLE_NAME,
            COL_GRANTEE,
            COL_PRIVILEGE,
            COL_GRANTABLE,
        ]
        if COL_TYPE in grants_columns:
            grants_select_cols.append(COL_TYPE)
        elif COL_HIERARCHY in grants_columns:
            grants_select_cols.append(COL_HIERARCHY)
        grants_query = (
            f"SELECT {', '.join(grants_select_cols)} "
            f"FROM {ALL_TAB_PRIVS_VIEW} WHERE {owner_col} = :{PARAM_SCHEMA_NAME} "
            f"{table_filters}"
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
