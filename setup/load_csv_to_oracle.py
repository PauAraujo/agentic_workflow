import csv
import sys
import json
import argparse
import oracledb

from typing import Any
from pathlib import Path
from datetime import datetime
from collections import defaultdict, deque

from sql_query_assistant.config import DatabaseSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "setup" / "data" / "oracle_exports"

SCHEMA_ORDER = ["ICSR_LOOKUP", "ICSR", "ICSR_EMA"]
#SCHEMA_ORDER = ["SQL_AI"]

DEFAULT_BATCH_SIZE = 1000

ORACLE_DATE_TYPES = ("DATE",)
ORACLE_NUMBER_TYPE = "NUMBER"


def get_connection() -> oracledb.Connection:
    """
    Open a connection to Oracle using credentials loaded from .env.
    """
    db = DatabaseSettings()
    dsn = oracledb.makedsn(
        db.oracle_host,
        db.oracle_port,
        service_name=db.oracle_service,
    )
    connection = oracledb.connect(
        user=db.oracle_user,
        password=db.oracle_password,
        dsn=dsn,
    )
    print("Connected to Oracle.")
    return connection



def _load_column_metadata(
    metadata: dict[str, Any],
) -> tuple[dict[str, dict[str, dict]], set[str]]:
    """
    Parse the `columns` section of a schema's metadata file.

    Builds a lookup of column types (used later to convert CSV strings to the
    right Python types) and identifies columns that must be excluded from
    INSERT statements because Oracle manages them automatically (identity
    columns, virtual/computed columns).

    Args:
        metadata: The parsed `_metadata.json` dict for a schema.

    Returns:
        A 2-tuple (column_types, columns_to_skip) where:
        - column_types: {table_name: {column_name: <column metadata dict>}}
        - columns_to_skip: set of "TABLE.COLUMN" strings to exclude from INSERTs.
    """
    column_types: dict[str, dict[str, dict]] = {}
    columns_to_skip: set[str] = set()

    for column in metadata.get("columns", []):
        table = column["table_name"]
        column_name = column["column_name"]

        if table not in column_types:
            column_types[table] = {}
        column_types[table][column_name] = column

        # Identity columns — cannot INSERT into these
        if column.get("identity_column") == "YES":
            columns_to_skip.add(f"{table}.{column_name}")
            continue

        # Virtual columns — heuristic: data_default contains double-quoted identifiers
        default = column.get("data_default")
        if default and '"' in default:
            columns_to_skip.add(f"{table}.{column_name}")

    return column_types, columns_to_skip


def _sort_tables_by_fk_dependencies(
    table_names: list[str],
    metadata: dict[str, Any] | None,
) -> list[str]:
    """
    Sort tables so that parent (referenced) tables come before their children.

    If table DOSE_FORM has a foreign key pointing to DOSE_FORM_CLASS, we must
    load DOSE_FORM_CLASS first, otherwise Oracle rejects the child rows with
    ORA-02291 (parent key not found).

    Builds a dependency graph from FK metadata and applies Kahn's topological
    sort (repeatedly pick tables whose parents have all been placed).  Ties
    are broken alphabetically for deterministic output.

    Falls back to plain alphabetical order when `metadata` is None or has
    no `foreign_keys` section.  Cycles (rare, but possible with deferred
    constraints) are handled by appending the remaining tables at the end.

    Args:
        table_names: List of table names to sort (one per CSV file found).
        metadata: The parsed `_metadata.json` dict, or None if unavailable.

    Returns:
        The same table names reordered so parents precede children.
    """
    if not metadata or "foreign_keys" not in metadata:
        return sorted(table_names)

    table_set = set(table_names)

    # Build adjacency: child -> set of parents (within same schema only)
    parents_of: dict[str, set[str]] = defaultdict(set)
    children_of: dict[str, set[str]] = defaultdict(set)

    for fk in metadata["foreign_keys"]:
        child = fk["table_name"]
        parent = fk["referenced_table"]
        # Only consider intra-schema edges where both tables are being loaded
        if child in table_set and parent in table_set and child != parent:
            parents_of[child].add(parent)
            children_of[parent].add(child)

    # Kahn's algorithm — pick tables whose parents are all resolved
    in_degree = {t: len(parents_of.get(t, set())) for t in table_names}
    queue: deque[str] = deque(
        sorted(t for t in table_names if in_degree[t] == 0)
    )
    ordered: list[str] = []

    while queue:
        table = queue.popleft()
        ordered.append(table)
        for child in sorted(children_of.get(table, [])):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    # If a cycle prevents full resolution, append remaining tables alphabetically
    if len(ordered) < len(table_names):
        remaining = sorted(set(table_names) - set(ordered))
        ordered.extend(remaining)

    return ordered


def _parse_date(value: str) -> datetime:
    """
    Convert an Oracle DATE string to a Python datetime.

    Oracle's DATE type always stores date *and* time, so exports may look like
    "2004-08-24" or "2004-08-24 11:56:53". Both forms are handled.
    """
    if " " in value or "T" in value:
        return datetime.fromisoformat(value.replace(" ", "T"))
    return datetime.strptime(value, "%Y-%m-%d")


def _parse_timestamp(value: str) -> datetime:
    """
    Convert an Oracle TIMESTAMP string to a Python datetime.

    Exported values look like "2017-11-22 11:10:46.301" (milliseconds) or
    "2021-03-16 16:00:18.669614" (microseconds). The space between date
    and time is replaced with T so fromisoformat can parse it.
    """
    return datetime.fromisoformat(value.replace(" ", "T"))


def _parse_number(value: str) -> int | float:
    """Convert an Oracle NUMBER string to int (if whole) or float (if decimal)."""
    if "." in value:
        return float(value)
    return int(value)


def _convert_row(
    row: dict[str, str],
    columns_to_insert: list[str],
    column_meta: dict[str, dict],
) -> list[Any]:
    """
    Convert one CSV row from raw strings into properly typed Python values.

    Each value is matched against its Oracle column type (from metadata) and
    converted accordingly: DATE/TIMESTAMP to datetime, NUMBER to
    int/float, everything else stays as a string.  Empty strings
    become None (SQL NULL). If conversion fails, the raw string is
    passed through and Oracle will attempt its own implicit conversion.

    Args:
        row: A single CSV row as a dict of {column_name: raw_string}.
        columns_to_insert: Ordered list of columns to include in the INSERT.
        column_meta: Column metadata for this table (from _load_column_metadata).

    Returns:
        List of typed Python values, one per column, in columns_to_insert order.
    """
    values: list[Any] = []
    for column_name in columns_to_insert:
        raw = row[column_name]

        # Empty string → NULL
        if raw == "":
            values.append(None)
            continue

        meta = column_meta.get(column_name, {})
        data_type = meta.get("data_type", "")

        try:
            if data_type in ORACLE_DATE_TYPES:
                values.append(_parse_date(raw))
            elif data_type.startswith("TIMESTAMP"):
                values.append(_parse_timestamp(raw))
            elif data_type == ORACLE_NUMBER_TYPE:
                values.append(_parse_number(raw))
            else:
                values.append(raw)
        except (ValueError, TypeError):
            # If conversion fails, pass as string and let Oracle handle it
            values.append(raw)

    return values


def load_table(
    connection: oracledb.Connection,
    schema_name: str,
    table_name: str,
    csv_path: Path,
    column_meta: dict[str, dict],
    columns_to_skip: set[str],
    batch_size: int,
) -> int:
    """
    Read one CSV file and INSERT its rows into the corresponding Oracle table.

    Columns that are virtual or identity (listed in columns_to_skip) are
    excluded from the INSERT. Rows are sent in batches via executemany
    for performance.

    Args:
        connection: An open Oracle connection.
        schema_name: Target schema (e.g. "SQL_AI").
        table_name: Target table (e.g. "DOSE_FORM").
        csv_path: Path to the CSV file to read.
        column_meta: Column metadata for this table (from _load_column_metadata).
        columns_to_skip: Set of "TABLE.COLUMN" strings to exclude.
        batch_size: Number of rows per executemany call.

    Returns:
        The total number of rows inserted.
    """
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            print(f"    SKIP {table_name}: empty CSV")
            return 0

        # Filter out virtual/identity columns
        columns_to_insert = [
            column for column in reader.fieldnames
            if f"{table_name}.{column}" not in columns_to_skip
        ]

        if not columns_to_insert:
            print(f"    SKIP {table_name}: no insertable columns")
            return 0

        # Build INSERT statement (schema-qualified)
        qualified_table = f"{schema_name}.{table_name}"
        column_list = ", ".join(columns_to_insert)
        placeholders = ", ".join(f":{i + 1}" for i in range(len(columns_to_insert)))
        insert_sql = f"INSERT INTO {qualified_table} ({column_list}) VALUES ({placeholders})"

        cursor = connection.cursor()
        try:
            batch: list[list[Any]] = []
            total_rows = 0

            for row in reader:
                values = _convert_row(row, columns_to_insert, column_meta)
                batch.append(values)

                if len(batch) >= batch_size:
                    cursor.executemany(insert_sql, batch)
                    total_rows += len(batch)
                    batch.clear()

            # Insert remaining rows
            if batch:
                cursor.executemany(insert_sql, batch)
                total_rows += len(batch)

            connection.commit()
        finally:
            cursor.close()

    return total_rows


def load_schema(
    connection: oracledb.Connection,
    schema_name: str,
    data_dir: Path,
    batch_size: int,
    metadata_schema: str | None = None,
    truncate_first: bool = False,
) -> None:
    """
    Load every CSV file for one schema into Oracle.

    Steps:

    1. Discover CSV files under data_dir/<schema_name>/.
    2. Load _metadata.json (from metadata_schema if given, otherwise
       from the target schema) for column types and FK info.
    3. Sort tables in FK dependency order (parents first).
    4. If truncate_first, empty all tables in reverse dependency order
       (children first) so foreign-key constraints are not violated.
    5. INSERT each table's CSV data in dependency order.

    Args:
        connection: An open Oracle connection.
        schema_name: Target schema (e.g. "SQL_AI").
        data_dir: Root directory containing one subdirectory per schema,
            each with CSV files and a _metadata.json inside.
        batch_size: Number of rows per executemany call.
        metadata_schema: If set, load metadata from this schema's directory
            instead of schema_name. Useful when the target schema is a
            copy of another (e.g. SQL_AI mirrors ICSR_LOOKUP).
        truncate_first: If True, TRUNCATE every table before inserting.
    """
    schema_csv_dir = data_dir / schema_name
    if not schema_csv_dir.exists():
        print(f"  No CSV directory for {schema_name}, skipping.")
        return

    csv_files_by_name: dict[str, Path] = {
        csv_file.stem: csv_file
        for csv_file in schema_csv_dir.iterdir()
        if csv_file.is_file() and csv_file.suffix.lower() == ".csv"
    }
    if not csv_files_by_name:
        print(f"  No CSV files in {schema_csv_dir}.")
        return

    # Load metadata for column type info
    metadata_schema_key = metadata_schema or schema_name
    metadata_path = data_dir / metadata_schema_key / "_metadata.json"
    if metadata_path.exists():
        with open(metadata_path, encoding="utf-8") as f:
            metadata = json.load(f)
        column_types, columns_to_skip = _load_column_metadata(metadata)
        if metadata_schema:
            print(f"  Using metadata from {metadata_schema}.")
    else:
        print(f"  WARNING: No metadata found at {metadata_path}, "
              "loading without type conversion or column filtering.")
        metadata = None
        column_types = {}
        columns_to_skip = set()

    # Sort tables so parents are loaded before children (avoids FK violations)
    table_order = _sort_tables_by_fk_dependencies(
        list(csv_files_by_name), metadata,
    )

    # Truncate in reverse dependency order (children first) so parent PKs
    # referenced by enabled FKs can be cleared without ORA-02266.
    if truncate_first:
        for table_name in reversed(table_order):
            qualified = f"{schema_name}.{table_name}"
            cursor = connection.cursor()
            try:
                cursor.execute(f"TRUNCATE TABLE {qualified}")
            except oracledb.DatabaseError as e:
                print(f"    TRUNCATE WARNING {table_name}: {e}", file=sys.stderr)
            finally:
                cursor.close()

    for table_name in table_order:
        csv_path = csv_files_by_name[table_name]
        column_meta = column_types.get(table_name, {})

        try:
            count = load_table(
                connection, schema_name, table_name, csv_path,
                column_meta, columns_to_skip, batch_size,
            )
            print(f"    {table_name}: {count} rows")
        except oracledb.DatabaseError as e:
            connection.rollback()
            print(f"    ERROR {table_name}: {e}", file=sys.stderr)



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load CSV exports into Oracle tables.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Directory with schema subdirs containing CSV files and "
             f"_metadata.json (default: {DEFAULT_DATA_DIR.relative_to(PROJECT_ROOT)})",
    )
    parser.add_argument(
        "--schemas",
        nargs="+",
        default=None,
        help=f"Schemas to load (default: {', '.join(SCHEMA_ORDER)})",
    )
    parser.add_argument(
        "--metadata-schema",
        default=None,
        help="Use another schema's _metadata.json (e.g. ICSR_LOOKUP for a "
             "SQL_AI copy). Provides column types and FK ordering.",
    )
    parser.add_argument(
        "--truncate-first",
        action="store_true",
        default=False,
        help="TRUNCATE each table before inserting (for clean re-loads).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Rows per INSERT batch (default: {DEFAULT_BATCH_SIZE})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    schemas = args.schemas or SCHEMA_ORDER

    connection = get_connection()
    try:
        for schema_name in schemas:
            print(f"\nLoading {schema_name} ...")
            load_schema(
                connection, schema_name, args.data_dir,
                args.batch_size,
                metadata_schema=args.metadata_schema,
                truncate_first=args.truncate_first,
            )
    finally:
        connection.close()

    print("Done.")


if __name__ == "__main__":
    main()
