import csv
import json
import argparse

from pathlib import Path
from typing import Any, Optional, Tuple

from sql_query_assistant.config import Settings


# Lookup column candidates for identifying key-value pairs in lookup tables
KEY_COLUMN_CANDIDATES = ["ID", "CODE"]
VALUE_COLUMN_CANDIDATES = ["NAME", "LABEL", "DESCRIPTION", "DESC", "TITLE"]
KEY_COLUMN_SUFFIXES = ["_CODE", "_ID"]  # prefer _CODE before _ID (e.g., SOC_CODE over RMS_ID)
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
# ≤50 rows: embed full map
# >50 rows: 15 samples + _value_column for JOIN guidance
FULL_EMBED_THRESHOLD = 50
SAMPLE_SIZE = 15

# Lookup schema name
LOOKUP_SCHEMA_NAME = "ICSR_LOOKUP"

# Table filtering patterns for text-to-SQL relevance
# These patterns identify operational/technical tables that are not useful for end-user queries
SKIP_TABLE_PREFIXES = (
    "TMP_",        # Temporary/staging tables
    "DD_",         # Deduplication tables (except DD_SAFETYREPORT_DUPLICATES - see KEEP list)
    "DDC_",        # Deduplication cluster tables
    "QRTZ_",       # Quartz scheduler tables
    "CT_",         # Empty clinical trial tables (ICSR_EMA)
    "MODEL_",      # ML model intermediates
    "INTERPRETATION_",  # Interpretation intermediates
    "REROUTED_MESSAGE",  # Message rerouting tables (ICSR_EMA)
    "EXPORT_REQUEST",    # Export plumbing tables (ICSR_EMA)
    "VW_R_AUTO_LOG",     # Log aggregation views (ICSR_EMA)
)

# Tables to explicitly KEEP even if they match skip patterns
KEEP_TABLES = {
    "DD_SAFETYREPORT_DUPLICATES",  # Master/duplicate relationships for deduplication
}

SKIP_TABLE_SUFFIXES = (
    "_RECODE",     # Recoding byproduct tables
    "_TMP",        # Temporary tables
    "_HIST",       # Historical audit tables (ICSR_EMA only)
    "_LOG",        # Logging tables
)

SKIP_TABLE_PATTERNS = (
    "_BK_",        # Backup tables (e.g., CASE_REPORT_BK_SCTASK0223177)
    "_BAK",        # Backup tables
)

# Exact table names to skip (across all schemas)
SKIP_TABLES_GLOBAL = {
    "MAP_TBL_COL",          # Technical metadata
    "MAP_TBL_SEQ",          # Technical metadata
    "TBL_STATS_EXPORT",     # Export statistics
    "UNIT_MISSPELLING",     # Spelling correction
    "CONFIG_PARAMETER",     # Operational config
    "QUALITY_ISSUE",        # Operational
    "CRITERIA",             # Operational config
    "SCHEMA_VERSION",       # Schema version metadata
}

# Tables to skip only in specific schemas
SKIP_TABLES_BY_SCHEMA = {
    "ICSR": {
        "TMP_REPORTER",     # Staging data
    },
    "ICSR_LOOKUP": {
        "ACCESS_LEVEL",     # Not referenced by core tables
        "ACCESS_RIGHT",     # System permissions, not clinical
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
        "DM_CONFIGURATION",       # Data management config
        "DM_MAPPING",             # Data management mapping
        "DM_EXTERNAL_DATA",       # Data management external
        "D_PROCEDURERESULTS",     # Procedure results (internal)
        "R_STATUS_PRODS",         # Status products (internal)
        "R_STATUS_SUBS",          # Status substances (internal)
        "ICSR_FIELD_NULL_FLAVOUR",  # Field metadata
        "ICSR_FIELD_OID",           # Field OIDs
        "VW_ORGANISATION_HQ",       # Org hierarchy view
        "VW_REPORTS_MLM",           # MLM reporting view
        "VW_SUBSTANCES_MLM",        # MLM substances view
        "ACTIVE_SUBSTANCE_MLM",     # MLM substance data
        "SAFETY_REPORT_COMMIT_ROLLBACK",  # Transactional tracking (empty)
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

    # Check prefix patterns
    for prefix in SKIP_TABLE_PREFIXES:
        if upper_name.startswith(prefix):
            return True

    # Check suffix patterns (HIST only for ICSR_EMA)
    for suffix in SKIP_TABLE_SUFFIXES:
        if suffix == "_HIST" and schema_name != "ICSR_EMA":
            continue
        if upper_name.endswith(suffix):
            return True

    # Check substring patterns
    for pattern in SKIP_TABLE_PATTERNS:
        if pattern in upper_name:
            return True

    # Check global skip list
    if upper_name in SKIP_TABLES_GLOBAL:
        return True

    # Check schema-specific skip list
    schema_skip_set = SKIP_TABLES_BY_SCHEMA.get(schema_name, set())
    if upper_name in schema_skip_set:
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
        "--value-map-threshold",
        type=int,
        default=FULL_EMBED_THRESHOLD,
        help=f"Max rows for lookup tables to embed full value_map (default: {FULL_EMBED_THRESHOLD}).",
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


def group_by_key(
    items: list[dict[str, Any]],
    key: str,
    sort_key: Optional[str] = None
) -> dict[str, list[dict[str, Any]]]:
    """Group items by a specified key with optional sorting."""
    grouped = {}
    for item in items:
        grouped.setdefault(item[key], []).append(item)

    if sort_key:
        for group_items in grouped.values():
            group_items.sort(key=lambda item: item.get(sort_key) or 0)

    return grouped


def build_type_string(column: dict[str, Any]) -> str:
    """Build a formatted type string from column metadata."""
    data_type = column.get(FIELD_DATA_TYPE) or ""
    precision = column.get("data_precision")
    scale = column.get("data_scale")
    char_length = column.get("char_length")
    data_length = column.get("data_length")

    if data_type in ORACLE_CHAR_TYPES:
        length = char_length or data_length
        return f"{data_type}({length})" if length else data_type
    if data_type == ORACLE_NUMBER_TYPE and precision is not None:
        if scale is not None:
            return f"{ORACLE_NUMBER_TYPE}({precision},{scale})"
        return f"{ORACLE_NUMBER_TYPE}({precision})"
    return data_type


def pick_lookup_columns(
    columns: list[dict[str, Any]],
    table_name: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """
    Identify key and value columns in a lookup table.

    Returns:
        Tuple of (key_column_name, value_column_name) or (None, None) if not found.
    """
    column_names = [col[FIELD_COLUMN_NAME] for col in columns]
    upper_names = [name.upper() for name in column_names]

    def find_candidate(base_candidates: list[str], suffixes: list[str]) -> Optional[str]:
        # First priority: column that matches table_name + suffix
        if table_name:
            upper_table = table_name.upper()
            for suffix in suffixes:
                table_specific_col = f"{upper_table}{suffix}"
                if table_specific_col in upper_names:
                    return column_names[upper_names.index(table_specific_col)]

        # Second priority: exact matches like "ID", "CODE"
        for candidate in base_candidates:
            if candidate in upper_names:
                return column_names[upper_names.index(candidate)]

        # Third priority: suffix patterns in order
        for suffix in suffixes:
            for upper_name, original_name in zip(upper_names, column_names):
                if upper_name.endswith(suffix):
                    return original_name

        return None

    key_column = find_candidate(KEY_COLUMN_CANDIDATES, KEY_COLUMN_SUFFIXES)
    value_column = find_candidate(VALUE_COLUMN_CANDIDATES, VALUE_COLUMN_SUFFIXES)

    # For two-column tables, use smart fallback
    if len(column_names) == 2:
        if not key_column and not value_column:
            key_column = column_names[0]
            value_column = column_names[1]
        elif key_column and not value_column:
            value_column = column_names[1] if column_names[0] == key_column else column_names[0]
        elif value_column and not key_column:
            key_column = column_names[0] if column_names[1] == value_column else column_names[1]

    if key_column and value_column and key_column != value_column:
        return key_column, value_column
    return None, None


def load_value_map_with_metadata(
    csv_path: Path,
    key_column: str,
    value_column: str,
    threshold: int,
    row_count: int,
) -> dict[str, Any]:
    """
    Load a value map from a CSV file with metadata.

    Strategy:
    - ≤threshold: full map + _count
    - >threshold: SAMPLE_SIZE samples + _count + _value_column

    Args:
        csv_path: Path to the CSV file
        key_column: Column name for keys
        value_column: Column name for values
        threshold: Max rows for full embed
        row_count: Total row count from metadata (required)

    Returns:
        Dictionary with value mappings and metadata (_count, optionally _value_column).
    """
    if row_count <= threshold:
        # Full embed - load all values
        value_map: dict[str, Any] = {"_count": row_count}
        with csv_path.open("r", encoding=UTF8_ENCODING, newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                key_value = row.get(key_column)
                value = row.get(value_column)
                if key_value is None or not str(key_value).strip():
                    continue
                if value is None or not str(value).strip():
                    continue
                value_map[str(key_value)] = str(value)
        return value_map
    else:
        # Partial sample - include _value_column for JOIN guidance
        value_map = {
            "_count": row_count,
            "_value_column": value_column,
        }
        samples_collected = 0
        with csv_path.open("r", encoding=UTF8_ENCODING, newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                key_value = row.get(key_column)
                value = row.get(value_column)
                if key_value is None or not str(key_value).strip():
                    continue
                if value is None or not str(value).strip():
                    continue
                value_map[str(key_value)] = str(value)
                samples_collected += 1
                if samples_collected >= SAMPLE_SIZE:
                    break
        return value_map


def build_column_fk_map(foreign_keys_rows: list[dict[str, Any]]) -> dict[Tuple[str, str], str]:
    """
    Build a mapping from (table_name, column_name) to compact FK string.

    Returns:
        Dict mapping (table, column) to "REF_SCHEMA.REF_TABLE.REF_COLUMN" strings.
    """
    # Group by (table_name, constraint_name) to handle composite FKs
    grouped = {}
    for row in foreign_keys_rows:
        composite_key = (row[FIELD_TABLE_NAME], row[FIELD_CONSTRAINT_NAME])
        grouped.setdefault(composite_key, []).append(row)

    # Build column-level FK mapping
    column_fk_map = {}
    for (table_name, _), rows in grouped.items():
        rows.sort(key=lambda r: r.get(FIELD_POSITION) or 0)
        for row in rows:
            column_name = row[FIELD_COLUMN_NAME]
            ref_schema = row[FIELD_R_OWNER]
            ref_table = row[FIELD_REFERENCED_TABLE]
            ref_column = row[FIELD_REFERENCED_COLUMN]
            # Compact FK format: "SCHEMA.TABLE.COLUMN"
            column_fk_map[(table_name, column_name)] = f"{ref_schema}.{ref_table}.{ref_column}"

    return column_fk_map


def get_table_row_count(tables: dict[str, list[dict[str, Any]]], table_name: str) -> Optional[int]:
    """Get row count for a table from tables metadata."""
    table_data = tables.get(table_name, [])
    return table_data[0].get(FIELD_NUM_ROWS) if table_data else None


def extract_primary_key_columns(
    constraints: list[dict[str, Any]],
    constraint_columns: dict[str, list[dict[str, Any]]]
) -> list[str]:
    """Extract primary key column names for a table."""
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
    threshold: int,
    overwrite: bool,
    filter_tables: bool = True,
    lookup_metadata: Optional[dict[str, Any]] = None,
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
    schema_tables = group_by_key(metadata.get("tables", []), FIELD_TABLE_NAME)
    schema_columns = group_by_key(metadata.get("columns", []), FIELD_TABLE_NAME)
    constraints_by_table = group_by_key(metadata.get("constraints", []), FIELD_TABLE_NAME)

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
    constraint_columns = group_by_key(
        metadata.get("constraint_columns", []),
        FIELD_CONSTRAINT_NAME,
        sort_key=FIELD_POSITION
    )
    column_fk_map = build_column_fk_map(metadata.get("foreign_keys", []))

    # Load ICSR_LOOKUP metadata for value_map generation (if processing different schema)
    lookup_tables = {}
    lookup_columns = {}
    if lookup_metadata:
        lookup_tables = group_by_key(lookup_metadata.get("tables", []), FIELD_TABLE_NAME)
        lookup_columns = group_by_key(lookup_metadata.get("columns", []), FIELD_TABLE_NAME)

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
        primary_key_columns = extract_primary_key_columns(table_constraints, constraint_columns)

        # Collect value_maps for deduplication at table level
        table_value_maps: dict[str, dict[str, str]] = {}

        # Build column metadata with compact FK and value_map_ref
        column_list = []
        for column in columns:
            column_name = column[FIELD_COLUMN_NAME]

            col_meta: dict[str, Any] = {
                "name": column_name,
                "type": build_type_string(column),
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
                            key_col, value_col = pick_lookup_columns(ref_columns, table_name=ref_table)

                            # Override key_col with the actual referenced column
                            if any(c.get(FIELD_COLUMN_NAME) == ref_column for c in ref_columns):
                                key_col = ref_column

                            if key_col and value_col:
                                csv_path = exports_dir / ref_schema / f"{ref_table}{CSV_EXTENSION}"
                                row_count = get_table_row_count(lookup_tables, ref_table)
                                if csv_path.exists() and row_count is not None:
                                    value_map = load_value_map_with_metadata(
                                        csv_path, key_col, value_col, threshold, row_count
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
        print(f"  Filtered: {cards_filtered} operational/technical tables (use --include-all to include)")
    if cards_skipped > 0:
        print(f"  Skipped: {cards_skipped} existing cards (use --overwrite to replace)")


def main():
    """Main entry point for table card generation."""
    args = parse_args()
    settings = Settings()

    # Resolve directory paths with defaults
    exports_dir = Path(args.exports_dir or settings.paths.input_dir / DB_EXPORTS_DIR)
    cards_dir = Path(args.cards_dir or settings.paths.table_cards_dir)

    # Determine which metadata files to process
    if args.metadata_file:
        metadata_paths = [Path(args.metadata_file)]
    elif args.schema:
        metadata_paths = [exports_dir / args.schema / METADATA_FILENAME]
    else:
        metadata_paths = sorted(exports_dir.glob(f"*/{METADATA_FILENAME}"))
        if not metadata_paths:
            raise ValueError("No metadata files found. Provide --schema or --metadata-file.")

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
        current_lookup_metadata = lookup_metadata if schema_name != LOOKUP_SCHEMA_NAME else None

        generate_table_cards(
            metadata,
            exports_dir,
            schema_cards_dir,
            threshold=args.value_map_threshold,
            overwrite=args.overwrite,
            filter_tables=not args.include_all,
            lookup_metadata=current_lookup_metadata,
        )

    print(f"\nTable card generation complete!")
    print(f"Output directory: {cards_dir}")


if __name__ == "__main__":
    main()
