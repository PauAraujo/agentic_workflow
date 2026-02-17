import csv
import json
import argparse

from typing import Any
from pathlib import Path

from sql_query_assistant.config import PathSettings

# Label-column heuristics for identifying human-readable values in lookup tables
VALUE_COLUMN_CANDIDATES = ["NAME", "LABEL", "DESCRIPTION", "DESC", "TITLE"]
VALUE_COLUMN_SUFFIXES = ["_NAME", "_DESC"]

# Metadata field names
FIELD_TABLE_NAME = "table_name"
FIELD_COLUMN_NAME = "column_name"
FIELD_CONSTRAINT_NAME = "constraint_name"
FIELD_CONSTRAINT_TYPE = "constraint_type"
FIELD_DATA_TYPE = "data_type"
FIELD_SCHEMA = "schema"
FIELD_COLUMNS = "columns"
FIELD_POSITION = "position"
FIELD_COMMENTS = "comments"
FIELD_NUM_ROWS = "num_rows"
FIELD_COLUMN_ID = "column_id"
FIELD_NULLABLE = "nullable"
FIELD_R_OWNER = "r_owner"
FIELD_REFERENCED_TABLE = "referenced_table"
FIELD_REFERENCED_COLUMN = "referenced_column"

# Oracle constraint types
CONSTRAINT_TYPE_PRIMARY = "P"
NULLABLE_YES = "Y"

# Oracle data types
ORACLE_CHAR_TYPES = ("VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR")
ORACLE_NUMBER_TYPE = "NUMBER"

# File/path constants
METADATA_FILENAME = "_metadata.json"
DB_EXPORTS_DIR = "db_exports"
JSON_EXTENSION = ".json"
CSV_EXTENSION = ".csv"
UTF8_ENCODING = "utf-8"

# Value map thresholds
# The presence/absence of _value_column serves as a semantic signal:
#   - _value_column ABSENT: all lookup values are embedded, use IDs directly
#   - _value_column PRESENT: only samples shown, JOIN on that column if value not found
# Threshold set to 500 to cover user-facing lookups (countries=259, outcomes, etc.)
FULL_EMBED_THRESHOLD = 500
SAMPLE_SIZE = 20

# Lookup schema name
LOOKUP_SCHEMA_NAME = "ICSR_LOOKUP"

# Table filtering patterns for text-to-SQL relevance
# These patterns identify operational/technical tables that are not useful for end-user queries
SKIP_TABLE_PREFIXES = (
    "TMP_",
    "DD_",
    "DDC_",
    "QRTZ_",
    "CT_",
    "MODEL_",
    "INTERPRETATION_",
    "REROUTED_MESSAGE",
    "EXPORT_REQUEST",
    "VW_R_AUTO_LOG",
)

# Tables to explicitly KEEP even if they match skip patterns
KEEP_TABLES = {
    "DD_SAFETYREPORT_DUPLICATES",  # Master/duplicate relationships for deduplication
}

SKIP_TABLE_SUFFIXES = (
    "_TMP",
    "_HIST",
    "_LOG",
    "_BAK",
)

SKIP_TABLE_PATTERNS = (
    "_BK_",
)

# Exact table names to skip (across all schemas)
SKIP_TABLES_GLOBAL = {
    "MAP_TBL_COL",
    "MAP_TBL_SEQ",
    "TBL_STATS_EXPORT",
    "UNIT_MISSPELLING",
    "CONFIG_PARAMETER",
    "QUALITY_ISSUE",
    "CRITERIA",
    "SCHEMA_VERSION",
}

# Tables to skip only in specific schemas
SKIP_TABLES_BY_SCHEMA = {
    "ICSR_LOOKUP": {
        "ACCESS_LEVEL",
        "ACCESS_RIGHT",
    },
    "ICSR_EMA": {
        "ACCESS_POLICY",
        "ACCESS_LEVEL_ICSR_FIELD",
        "ROLE_ACCESS_RIGHT",
        "L2B_ACCESS_LOG",
        "MESSAGE_EXCHANGE",
        "MESSAGE_AUDITING",
        "MESSAGING_QUEUE_SUPPORT",
        "ORGANISATION_REROUTING",
        "NCA_REROUTING_COUNTRY",
        "NCA_SUSAR_REROUTING_COUNTRY",
        "NCA_SUSAR_ROUTING_COUNTRY",
        "REPORT_CATEGORY_ORG",
        "APP_COMPONENT_DOWNTIME",
        "DOCUMENT_DMS_MAPPING",
        "DM_CONFIGURATION",
        "DM_MAPPING",
        "DM_EXTERNAL_DATA",
        "D_PROCEDURERESULTS",
        "R_STATUS_PRODS",
        "R_STATUS_SUBS",
        "ICSR_FIELD_NULL_FLAVOUR",
        "ICSR_FIELD_OID",
        "VW_ORGANISATION_HQ",
        "VW_REPORTS_MLM",
        "VW_SUBSTANCES_MLM",
        "ACTIVE_SUBSTANCE_MLM",
        "SAFETY_REPORT_COMMIT_ROLLBACK",
    },
}


def should_skip_table(table_name: str, schema_name: str) -> bool:
    """
    Determine if a table should be skipped for table card generation.

    Skips operational, staging, backup, and algorithm-output tables that
    are not useful for end-user text-to-SQL queries.

    Args:
        table_name: Name of the table
        schema_name: Name of the schema

    Returns:
        True if the table should be skipped, False otherwise
    """
    upper_name = table_name.upper()

    # Check explicit KEEP list first (overrides skip patterns)
    if upper_name in KEEP_TABLES:
        return False

    # Cheap exact-match checks before loop-based pattern checks
    if upper_name in SKIP_TABLES_GLOBAL:
        return True
    if upper_name in SKIP_TABLES_BY_SCHEMA.get(schema_name, set()):
        return True

    # Check prefix patterns
    for prefix in SKIP_TABLE_PREFIXES:
        if upper_name.startswith(prefix):
            return True

    # Check suffix patterns
    for suffix in SKIP_TABLE_SUFFIXES:
        if upper_name.endswith(suffix):
            return True

    # Check substring patterns
    for pattern in SKIP_TABLE_PATTERNS:
        if pattern in upper_name:
            return True

    return False


def parse_args():
    """Parse command line arguments for table card generation."""
    parser = argparse.ArgumentParser(
        description="Generate optimized table card JSON files from Oracle metadata exports."
    )
    parser.add_argument(
        "--schema",
        default=None,
        help="Schema name to generate cards for (defaults to all schemas).",
    )
    parser.add_argument(
        "--exports-dir",
        default=None,
        help=f"Base exports directory (defaults to input/{DB_EXPORTS_DIR}).",
    )
    parser.add_argument(
        "--metadata-file",
        default=None,
        help=f"Path to {METADATA_FILENAME} (defaults to exports-dir/<SCHEMA>/{METADATA_FILENAME}).",
    )
    parser.add_argument(
        "--cards-dir",
        default=None,
        help="Output directory for table cards (defaults to input/table_cards).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing table cards.",
    )
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="Include all tables (skip filtering of operational/technical tables).",
    )
    return parser.parse_args()


def load_metadata(path: Path) -> dict[str, Any]:
    """Load metadata from a JSON file."""
    with path.open("r", encoding=UTF8_ENCODING) as handle:
        return json.load(handle)


def group_rows_by_field(
    items: list[dict[str, Any]], key: str, sort_key: str | None = None
) -> dict[str, list[dict[str, Any]]]:
    """
    Group a flat list of dicts into buckets that share the same *key* value.

    Args:
        items: Flat list of dicts (e.g. column metadata rows).
        key: Dict key whose value becomes the grouping key (e.g. "table_name").
        sort_key: If given, each group is sorted ascending by this numeric field
            (missing values default to 0).

    Returns:
        Mapping of group value to the list of dicts that share it,
        e.g. ``{"MY_TABLE": [row1, row2, ...]}``.
    """
    # Build buckets: each unique value of row[key] gets its own list.
    # E.g. key="table_name" turns [{"table_name": "DRUG", ...}, {"table_name": "DRUG", ...}]
    #   into {"DRUG": [{...}, {...}]}
    grouped = {}
    for row in items:
        grouped.setdefault(row[key], []).append(row)

    # Optionally sort each bucket by a numeric field (e.g. "position")
    if sort_key:
        for rows in grouped.values(): # sort in-place each bucket by the given sort_key
            rows.sort(key=lambda row: row.get(sort_key, 0)) # missing value gloat to the front of the list

    return grouped


def format_column_type(column: dict[str, Any]) -> str:
    """
    Format an Oracle column's data type into a human-readable string.

    Appends length or precision/scale qualifiers where applicable:
      - VARCHAR2(200), NCHAR(10)   character types get a length qualifier
      - NUMBER(10,2), NUMBER(5)    NUMBER gets precision and optional scale
      - DATE, CLOB, ...            all other types are returned as-is

    Args:
        column: A single column metadata dict from the Oracle export.

    Returns:
        Formatted type string, e.g. "VARCHAR2(200)" or "NUMBER(10,2)".
    """
    data_type = column.get(FIELD_DATA_TYPE) or ""
    precision = column.get("data_precision")
    scale = column.get("data_scale")
    char_length = column.get("char_length")
    data_length = column.get("data_length")

    # Character types: prefer char_length (semantic), fall back to data_length (byte-based)
    if data_type in ORACLE_CHAR_TYPES:
        length = char_length or data_length
        return f"{data_type}({length})" if length else data_type

    # NUMBER with explicit precision: include scale only when defined
    if data_type == ORACLE_NUMBER_TYPE and precision is not None:
        if scale is not None:
            return f"{ORACLE_NUMBER_TYPE}({precision},{scale})"
        return f"{ORACLE_NUMBER_TYPE}({precision})"

    # Everything else (DATE, CLOB, BLOB, TIMESTAMP, etc.)
    return data_type


def pick_label_column(
    columns: list[dict[str, Any]],
    table_name: str | None = None,
    key_column: str | None = None,
) -> str | None:
    """
    Identify which column in a lookup table holds the human-readable label.

    Lookup tables translate numeric codes into text (e.g. 78 → "France").
    The code/key column is typically already known from FK metadata; this
    function figures out which of the remaining columns is the readable name.

    Tries, in order:
      1. Table-name match    e.g. COUNTRY → COUNTRY_NAME
      2. Suffix match        any column ending in _NAME or _DESC
      3. Generic exact       NAME, LABEL, DESCRIPTION
      4. Two-column tables   if only two columns, the label is "the other one"

    Args:
        columns:     Column metadata dicts (must contain "column_name").
        table_name:  Lookup table name; enables tier 1.
        key_column:  Known key column to exclude from candidates.

    Returns:
        Column name (original casing), or None if no label column found.
    """
    column_names = [col[FIELD_COLUMN_NAME] for col in columns]

    # Build a case-insensitive index: "COUNTRY_NAME" → "Country_Name" (original)
    name_lookup = {name.upper(): name for name in column_names}
    upper_key = key_column.upper() if key_column else None

    def _is_valid(col_upper: str) -> bool:
        """A candidate is valid if it isn't the key column we already know."""
        return upper_key is None or col_upper != upper_key

    # 1) Table-name match: e.g. COUNTRY table → look for COUNTRY_NAME
    if table_name:
        upper_table = table_name.upper()
        for suffix in VALUE_COLUMN_SUFFIXES:
            candidate = f"{upper_table}{suffix}" # We match in UPPER,
            original = name_lookup.get(candidate)
            if original is not None and _is_valid(original.upper()):
                return original # but return the original form for downstream code

    # 2) suffix match: first column ending in _NAME or _DESC wins
    for suffix in VALUE_COLUMN_SUFFIXES:
        for upper_name, original in name_lookup.items():
            if upper_name.endswith(suffix) and _is_valid(upper_name):
                return original

    # 3) generic exact: bare column names like NAME, LABEL, DESCRIPTION
    for candidate in VALUE_COLUMN_CANDIDATES:
        original = name_lookup.get(candidate)
        if original is not None and _is_valid(original.upper()):
            return original

    # 4) two-column fallback: if we know the key, the label must be
    # the other column. Works because callers sort by COLUMN_ID first.
    if len(column_names) == 2 and key_column:
        other = column_names[1] if column_names[0] == key_column else column_names[0]
        if other != key_column:
            return other

    return None


def build_value_map_from_csv(
    csv_path: Path,
    key_column: str,
    value_column: str,
    row_count: int,
) -> dict[str, Any]:
    """
    Build a value map from a CSV export of a lookup table.

    The returned dict mixes `_`-prefixed metadata keys with data entries:

        {"_count": 500, "_value_column": "NAME", "1": "Headache", "2": "Nausea", ...}

    Small tables (≤ FULL_EMBED_THRESHOLD rows): all entries embedded, no
    `_value_column` → LLM can use IDs directly.
    Large tables (> FULL_EMBED_THRESHOLD rows): SAMPLE_SIZE entries, plus
    `_value_column` → LLM knows a JOIN may be needed.

    Args:
        csv_path: Path to the CSV file
        key_column: Column name for keys (e.g. "COUNTRY_ID")
        value_column: Column name for values (e.g. "COUNTRY_NAME")
        row_count: Total row count from Oracle metadata

    Returns:
        Dict with value mappings and metadata, or `{}` if no valid
        entries were found.
    """
    is_sampled = row_count > FULL_EMBED_THRESHOLD
    max_entries = SAMPLE_SIZE if is_sampled else None

    value_map: dict[str, Any] = {"_count": row_count} # e.g., value_map looks like {"_count": 102}
    if is_sampled:
        value_map["_value_column"] = value_column
        # now value_map = {"_count": 102, "_value_column": "NAME"}
        # {"_count": 102, "_value_column": "NAME", "1": "Headache", ...}

    # Read key->value pairs from the CSV, skipping rows with blank keys or values
    entries_added = 0
    with csv_path.open("r", encoding=UTF8_ENCODING, newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            row_key = row.get(key_column) # key_column='UNIT_ID -> row_key='1'
            row_value = row.get(value_column) # value_column='UNIT_NAME' -> row_value='Milligram'
            # Skip rows with blank keys or values
            if not row_key or not row_key.strip():
                continue
            if not row_value or not row_value.strip():
                continue
            # store the cleaned version
            value_map[row_key.strip()] = row_value.strip()
            entries_added += 1
            if max_entries is not None and entries_added >= max_entries:
                break

    if entries_added == 0:
        return {} # no entries, get discarded down the line

    return value_map


def build_column_fk_map(
    foreign_keys_rows: list[dict[str, Any]],
) -> dict[tuple[str, str], str]:
    """
    Build a lookup from (table, column) to the foreign table it points at.

    Each FK row from Oracle maps one source column to one referenced column.
    Composite FKs (e.g. COUNTRY_ID + REGION_ID) appear as separate rows
    sharing a constraint name — but since we map per-column, each row is
    processed independently and composites are handled naturally.

        Where the FK lives               Where it points to
        (source_table, source_column)  → "ref_schema.ref_table.ref_column"
        ("CASE",       "COUNTRY_ID")   → "ICSR_LOOKUP.COUNTRY.ID"
        ("CASE",       "STATUS_CODE")  → "ICSR_LOOKUP.STATUS.CODE"

    Args:
        foreign_keys_rows: Raw FK rows from Oracle metadata export.

    Returns:
        Dict mapping (table_name, column_name) to
        "REF_SCHEMA.REF_TABLE.REF_COLUMN" strings.
    """
    column_fk_map = {}
    for row in foreign_keys_rows:
        # Key: which column has the FK  (e.g. ("CASE", "COUNTRY_ID"))
        source = (row[FIELD_TABLE_NAME], row[FIELD_COLUMN_NAME])
        # Value: where it points to      (e.g. "ICSR_LOOKUP.COUNTRY.ID")
        target = f"{row[FIELD_R_OWNER]}.{row[FIELD_REFERENCED_TABLE]}.{row[FIELD_REFERENCED_COLUMN]}"
        column_fk_map[source] = target
    # Example: {('ACTIVE_SUBSTANCE', 'STRENGTH_UNIT_ID'): 'ICSR_LOOKUP.UNIT.UNIT_ID'}
    return column_fk_map


def get_table_row_count(
    tables: dict[str, list[dict[str, Any]]], table_name: str
) -> int | None:
    """
    Look up how many rows a table has, according to Oracle metadata.
    The `tables` dict maps table names to their metadata rows.
    We grab the first row's `num_rows` field

    Args:
        tables: Grouped tables metadata (from group_rows_by_field on FIELD_TABLE_NAME)
                Table name maps to list of metadata rows, e.g:
                {"COUNTRY": [{"table_name": "COUNTRY", "num_rows": 250, ...}]}
        table_name: Name of the table to get row count for (e.g. "ACTIVE_SUBSTANCE")

    Returns:
        Number of rows in the table, or None if not found.
    """
    table_data = tables.get(table_name, [])
    return table_data[0].get(FIELD_NUM_ROWS) if table_data else None


def extract_primary_key_columns(
    constraints: list[dict[str, Any]],
    constraint_columns: dict[str, list[dict[str, Any]]],
) -> list[str]:
    """
    Extract primary key column names for a table.

    Finds the first constraint with type "P" (Oracle's primary key marker)
    and returns its column names. Returns [] if no PK exists.

    Args:
        constraints: Constraint rows for this table, e.g.
            [{"constraint_name": "PK_CASE", "constraint_type": "P"}, ...]
        constraint_columns: Constraint name → its column rows, e.g.
            {"PK_CASE": [{"column_name": "CASE_ID"}, ...]}
    """
    for constraint in constraints:
        if constraint.get(FIELD_CONSTRAINT_TYPE) == CONSTRAINT_TYPE_PRIMARY:
            constraint_name = constraint.get(FIELD_CONSTRAINT_NAME)
            return [
                row[FIELD_COLUMN_NAME]
                for row in constraint_columns.get(constraint_name, [])
            ]
    return []


def generate_table_cards(
    metadata: dict[str, Any],
    exports_dir: Path,
    cards_dir: Path,
    overwrite: bool,
    filter_tables: bool = True,
    lookup_metadata: dict[str, Any] | None = None,
):
    """
    Generate optimized table card JSON files from metadata.

    Key improvements over previous version:
    1. Only generates cards for tables in the current schema (fixes misplacement bug)
    2. Adds qualified_name to table_metadata
    3. Uses compact FK notation at column level only (no top-level foreign_keys)
    4. Deduplicates value_maps at table level
    """
    schema_name = metadata[FIELD_SCHEMA]
    print(f"\nProcessing schema: {schema_name}")

    # Index metadata by table name - ONLY for current schema
    schema_tables = group_rows_by_field(metadata.get("tables", []), FIELD_TABLE_NAME)
    schema_columns = group_rows_by_field(metadata.get("columns", []), FIELD_TABLE_NAME)
    constraints_by_table = group_rows_by_field(
        metadata.get("constraints", []), FIELD_TABLE_NAME
    )

    # Build lookup dictionaries for comments (current schema only)
    table_comments = {
        row[FIELD_TABLE_NAME]: row.get(FIELD_COMMENTS)
        for row in metadata.get("table_comments", [])
    }
    column_comments = {
        (row[FIELD_TABLE_NAME], row[FIELD_COLUMN_NAME]): row.get(FIELD_COMMENTS)
        for row in metadata.get("column_comments", [])
    }

    # Build constraint columns and FK mappings
    constraint_columns = group_rows_by_field(
        metadata.get("constraint_columns", []),
        FIELD_CONSTRAINT_NAME,
        sort_key=FIELD_POSITION,
    )
    column_fk_map = build_column_fk_map(metadata.get("foreign_keys", []))

    # Load ICSR_LOOKUP metadata for value_map generation (if processing different schema)
    lookup_tables = {}
    lookup_columns = {}
    if lookup_metadata:
        lookup_tables = group_rows_by_field(
            lookup_metadata.get("tables", []), FIELD_TABLE_NAME
        )
        lookup_columns = group_rows_by_field(
            lookup_metadata.get("columns", []), FIELD_TABLE_NAME
        )

    cards_dir.mkdir(parents=True, exist_ok=True)

    # Track statistics
    cards_generated = 0
    cards_skipped = 0
    cards_filtered = 0

    # Generate table cards - ONLY for tables in the current schema
    for table_name in schema_columns.keys():
        # Apply table filtering if enabled
        if filter_tables and should_skip_table(table_name, schema_name):
            cards_filtered += 1
            continue

        columns = schema_columns[table_name]
        columns.sort(key=lambda col: col.get(FIELD_COLUMN_ID) or 0)

        # Extract primary key columns
        table_constraints = constraints_by_table.get(table_name, [])
        primary_key_columns = extract_primary_key_columns(
            table_constraints, constraint_columns
        )

        # Collect value_maps for deduplication at table level
        table_value_maps: dict[str, dict[str, str]] = {}

        # Build column metadata with compact FK and value_map_ref
        column_list = []
        for column in columns:
            column_name = column[FIELD_COLUMN_NAME]

            col_meta: dict[str, Any] = {
                "name": column_name,
                "type": format_column_type(column),
                "nullable": column.get(FIELD_NULLABLE) == NULLABLE_YES,
            }

            # Add description if non-empty
            description = column_comments.get((table_name, column_name)) or ""
            if description:
                col_meta["description"] = description

            # Add compact FK reference if this column is a foreign key
            fk_ref = column_fk_map.get((table_name, column_name))
            if fk_ref:
                col_meta["fk"] = fk_ref

                # Try to generate value_map for ICSR_LOOKUP references
                ref_parts = fk_ref.split(".")
                if len(ref_parts) == 3:
                    ref_schema, ref_table, ref_column = ref_parts

                    if ref_schema == LOOKUP_SCHEMA_NAME:
                        # Check if we already have this value_map
                        if ref_table not in table_value_maps:
                            # Try to load value_map from CSV
                            ref_columns = lookup_columns.get(ref_table, [])
                            ref_col_exists = any(
                                c.get(FIELD_COLUMN_NAME) == ref_column
                                for c in ref_columns
                            )
                            key_col = ref_column if ref_col_exists else None
                            value_col = pick_label_column(
                                ref_columns,
                                table_name=ref_table,
                                key_column=key_col,
                            )

                            if key_col and value_col:
                                csv_path = (
                                    exports_dir
                                    / ref_schema
                                    / f"{ref_table}{CSV_EXTENSION}"
                                )
                                row_count = get_table_row_count(
                                    lookup_tables, ref_table
                                )
                                if csv_path.exists() and row_count is not None:
                                    value_map = build_value_map_from_csv(
                                        csv_path, key_col, value_col, row_count
                                    )
                                    if value_map:
                                        table_value_maps[ref_table] = value_map

                        # Add reference to the value_map
                        if ref_table in table_value_maps:
                            col_meta["value_map_ref"] = ref_table

            column_list.append(col_meta)

        # Build the optimized table card structure
        table_card = {
            "table_metadata": {
                "qualified_name": f"{schema_name}.{table_name}",
                "schema_name": schema_name,
                "name": table_name,
                "primary_key": primary_key_columns,
                "row_count": get_table_row_count(schema_tables, table_name),
            },
            "columns": column_list,
        }

        # Add table description if non-empty
        table_description = table_comments.get(table_name) or ""
        if table_description:
            table_card["table_metadata"]["description"] = table_description

        # Add deduplicated value_maps at table level (if any)
        if table_value_maps:
            table_card["value_maps"] = table_value_maps

        # Write table card to file (always lowercase)
        filename = f"{table_name.lower()}{JSON_EXTENSION}"
        output_path = cards_dir / filename

        if output_path.exists() and not overwrite:
            cards_skipped += 1
            continue

        with output_path.open("w", encoding=UTF8_ENCODING) as handle:
            json.dump(table_card, handle, indent=2)
        cards_generated += 1

    print(f"  Generated: {cards_generated} table cards")
    if cards_filtered > 0:
        print(
            f"  Filtered: {cards_filtered} operational/technical tables (use --include-all to include)"
        )
    if cards_skipped > 0:
        print(f"  Skipped: {cards_skipped} existing cards (use --overwrite to replace)")


def main():
    """Main entry point for table card generation."""
    args = parse_args()
    paths = PathSettings()

    # Resolve directory paths with defaults
    exports_dir = Path(args.exports_dir or paths.input_dir / DB_EXPORTS_DIR)
    cards_dir = Path(args.cards_dir or paths.table_cards_dir)

    # Determine which metadata files to process
    if args.metadata_file:
        metadata_paths = [Path(args.metadata_file)]
    elif args.schema:
        metadata_paths = [exports_dir / args.schema / METADATA_FILENAME]
    else:
        metadata_paths = sorted(exports_dir.glob(f"*/{METADATA_FILENAME}"))
        if not metadata_paths:
            raise ValueError(
                "No metadata files found. Provide --schema or --metadata-file."
            )

    # Pre-load ICSR_LOOKUP metadata for value_map generation
    lookup_metadata_path = exports_dir / LOOKUP_SCHEMA_NAME / METADATA_FILENAME
    lookup_metadata = None
    if lookup_metadata_path.exists():
        lookup_metadata = load_metadata(lookup_metadata_path)
        print(f"Loaded ICSR_LOOKUP metadata for value_map generation")

    # Process each metadata file
    for metadata_path in metadata_paths:
        metadata = load_metadata(metadata_path)
        schema_name = metadata[FIELD_SCHEMA]
        schema_cards_dir = cards_dir / schema_name

        # Pass lookup_metadata only if processing a different schema
        current_lookup_metadata = (
            lookup_metadata if schema_name != LOOKUP_SCHEMA_NAME else None
        )

        generate_table_cards(
            metadata,
            exports_dir,
            schema_cards_dir,
            overwrite=args.overwrite,
            filter_tables=not args.include_all,
            lookup_metadata=current_lookup_metadata,
        )

    print(f"\nTable card generation complete!")
    print(f"Output directory: {cards_dir}")


if __name__ == "__main__":
    main()
