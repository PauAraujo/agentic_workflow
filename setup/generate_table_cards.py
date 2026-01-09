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
FIELD_REFERENCES = "references"
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

# Default thresholds
DEFAULT_VALUE_MAP_THRESHOLD = 100

# Lookup schema name
LOOKUP_SCHEMA_NAME = "ICSR_LOOKUP"


def parse_args():
    """
    Parse command line arguments for table card generation.

    Returns:
        argparse.Namespace: Parsed command line arguments.
    """
    parser = argparse.ArgumentParser(
        description="Generate table card JSON files from Oracle metadata exports."
    )
    parser.add_argument(
        "--schema",
        default=None,
        help="Schema name to generate cards for (defaults to metadata schema).",
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
        default=DEFAULT_VALUE_MAP_THRESHOLD,
        help=f"Max rows for ICSR_LOOKUP tables to embed value_map (default: {DEFAULT_VALUE_MAP_THRESHOLD}, 0 disables).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing table cards.",
    )
    parser.add_argument(
        "--lowercase-filenames",
        action="store_true",
        help="Write files as lowercase table names (default).",
    )
    parser.add_argument(
        "--lookup-strategy",
        choices=["full", "lightweight", "none"],
        default="full",
        help="Strategy for embedding lookup table data: 'full' embeds complete value maps (or samples if exceeds threshold), 'lightweight' includes row count and samples only, 'none' skips lookup metadata (default: full).",
    )
    parser.set_defaults(lowercase_filenames=True)
    return parser.parse_args()


def load_metadata(path: Path) -> dict[str, Any]:
    """
    Load metadata from a JSON file.

    Args:
        path: Path to the metadata JSON file.

    Returns:
        dictionary containing the metadata.
    """
    with path.open("r", encoding=UTF8_ENCODING) as handle:
        return json.load(handle)


def group_by_key(items: list[dict[str, Any]], key: str, sort_key: Optional[str] = None) -> dict[str, list[dict[str, Any]]]:
    """
    Group items by a specified key with optional sorting.

    Args:
        items: list of dictionaries to group.
        key: The key to group by.
        sort_key: Optional key to sort grouped items by.

    Returns:
        dictionary mapping key values to lists of items.
    """
    grouped = {}
    for item in items:
        grouped.setdefault(item[key], []).append(item)

    if sort_key:
        for group_items in grouped.values():
            group_items.sort(key=lambda item: item.get(sort_key) or 0)

    return grouped


def build_type_string(column: dict[str, Any]) -> str:
    """
    Build a formatted type string from column metadata.

    Args:
        column: dictionary containing column metadata with data_type, precision, scale, etc.

    Returns:
        Formatted type string (e.g., "VARCHAR2(100)", "NUMBER(10,2)").
    """
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


def pick_lookup_columns(columns: list[dict[str, Any]], table_name: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """
    Identify key and value columns in a lookup table.

    Attempts to identify appropriate key-value column pairs for lookup tables
    by checking common naming patterns (ID/CODE for keys, NAME/DESC for values).
    Prioritizes columns that match the table name (e.g., TIME_INTERVAL_ID for TIME_INTERVAL table).

    Args:
        columns: list of column metadata dictionaries.
        table_name: Optional table name to help identify the primary key column.

    Returns:
        Tuple of (key_column_name, value_column_name) or (None, None) if no suitable pair found.
    """
    column_names = [col[FIELD_COLUMN_NAME] for col in columns]
    upper_names = [name.upper() for name in column_names]

    def find_candidate(base_candidates: list[str], suffixes: list[str]) -> Optional[str]:
        """Find the first matching candidate, prioritizing table name matches."""
        # First priority: column that matches table_name + suffix (e.g., TIME_INTERVAL_ID for TIME_INTERVAL table)
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

    # For two-column tables, use smart fallback based on what was found
    if len(column_names) == 2:
        if not key_column and not value_column:
            # Neither found: use positional (first=key, second=value)
            key_column = column_names[0]
            value_column = column_names[1]
        elif key_column and not value_column:
            # Found key: use the other column as value
            value_column = column_names[1] if column_names[0] == key_column else column_names[0]
        elif value_column and not key_column:
            # Found value: use the other column as key (don't overwrite value_column!)
            key_column = column_names[0] if column_names[1] == value_column else column_names[1]

    if key_column and value_column and key_column != value_column:
        return key_column, value_column
    return None, None


def load_value_map(csv_path: Path, key_column: str, value_column: str, threshold: int) -> Optional[dict[str, str]]:
    """
    Load a value map from a CSV file with a row threshold.

    Args:
        csv_path: Path to the CSV file.
        key_column: Name of the key column.
        value_column: Name of the value column.
        threshold: Maximum number of rows to load. Returns None if exceeded.

    Returns:
        dictionary mapping keys to values, or None if row count exceeds threshold.
    """
    value_map = {}
    with csv_path.open("r", encoding=UTF8_ENCODING, newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=1):
            if index > threshold:
                return None
            key_value = row.get(key_column)
            value = row.get(value_column)
            # Skip rows with None, empty string, or whitespace-only keys/values
            if key_value is None or not str(key_value).strip() or value is None or not str(value).strip():
                continue
            value_map[str(key_value)] = str(value)
    return value_map


def load_sample_values(csv_path: Path, key_column: str, value_column: str, sample_size: int = 5) -> list[dict[str, str]]:
    """
    Load sample key-value pairs from a CSV file.

    Args:
        csv_path: Path to the CSV file.
        key_column: Name of the key column.
        value_column: Name of the value column.
        sample_size: Number of sample rows to load (default: 5).

    Returns:
        list of dictionaries containing sample key-value pairs.
    """
    samples = []
    with csv_path.open("r", encoding=UTF8_ENCODING, newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            key_value = row.get(key_column)
            value = row.get(value_column)
            # Skip rows with None, empty string, or whitespace-only keys/values
            if key_value is None or not str(key_value).strip() or value is None or not str(value).strip():
                continue
            samples.append({"key": str(key_value), "value": str(value)})
            if len(samples) >= sample_size:
                break
    return samples


def build_foreign_keys(foreign_keys_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """
    Build foreign key metadata grouped by table name.

    Args:
        foreign_keys_rows: list of foreign key constraint rows from metadata.

    Returns:
        dictionary mapping table names to lists of foreign key definitions.
    """
    # Group by (table_name, constraint_name) composite key
    grouped = {}
    for row in foreign_keys_rows:
        composite_key = (row[FIELD_TABLE_NAME], row[FIELD_CONSTRAINT_NAME])
        grouped.setdefault(composite_key, []).append(row)

    # Build foreign key structures
    foreign_keys_by_table = {}
    for (table_name, constraint_name), rows in grouped.items():
        rows.sort(key=lambda r: r.get(FIELD_POSITION) or 0)
        foreign_keys_by_table.setdefault(table_name, []).append(
            {
                FIELD_COLUMNS: [r[FIELD_COLUMN_NAME] for r in rows],
                FIELD_REFERENCES: {
                    FIELD_SCHEMA: rows[0][FIELD_R_OWNER],
                    "table": rows[0][FIELD_REFERENCED_TABLE],
                    FIELD_COLUMNS: [r[FIELD_REFERENCED_COLUMN] for r in rows],
                },
            }
        )
    return foreign_keys_by_table


def _get_table_row_count(tables: dict[str, list[dict[str, Any]]], table_name: str) -> Optional[int]:
    """
    Get row count for a table from tables metadata.

    Args:
        tables: dictionary of table metadata indexed by table name.
        table_name: Name of the table.

    Returns:
        Row count for the table, or None if not available.
    """
    table_data = tables.get(table_name, [])
    return table_data[0].get(FIELD_NUM_ROWS) if table_data else None


def _extract_primary_key_columns(
    constraints: list[dict[str, Any]],
    constraint_columns: dict[str, list[dict[str, Any]]]
) -> list[str]:
    """
    Extract primary key column names for a table.

    Args:
        constraints: list of all constraints for the table.
        constraint_columns: dictionary mapping constraint names to their columns.

    Returns:
        list of primary key column names.
    """
    for constraint in constraints:
        if constraint.get(FIELD_CONSTRAINT_TYPE) == CONSTRAINT_TYPE_PRIMARY:
            constraint_name = constraint.get(FIELD_CONSTRAINT_NAME)
            return [
                row[FIELD_COLUMN_NAME]
                for row in constraint_columns.get(constraint_name, [])
            ]
    return []


def _generate_lookup_metadata_for_column(
    foreign_key: dict[str, Any],
    tables: dict[str, list[dict[str, Any]]],
    columns_by_table: dict[str, list[dict[str, Any]]],
    exports_dir: Path,
    threshold: int,
    lookup_strategy: str,
    ref_column: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """
    Generate lookup table metadata for a foreign key column based on the selected strategy.

    Args:
        foreign_key: Foreign key definition containing references.
        tables: dictionary of table metadata indexed by table name.
        columns_by_table: dictionary of columns indexed by table name.
        exports_dir: Base directory containing exported CSV files.
        threshold: Maximum table size for value map inclusion.
        lookup_strategy: Strategy to use:
            - 'full': Embed complete value_map if within threshold, otherwise fall back to value_map_partial with samples
            - 'lightweight': Always embed row_count and sample values only
            - 'none': Skip all lookup metadata

    Returns:
        dictionary with lookup metadata, or None if not applicable.
    """
    # Skip if strategy is 'none'
    if lookup_strategy == "none":
        return None

    if threshold <= 0:
        return None

    ref_schema = foreign_key[FIELD_REFERENCES][FIELD_SCHEMA]
    ref_table = foreign_key[FIELD_REFERENCES]["table"]

    # Only embed lookup metadata for ICSR_LOOKUP tables
    if ref_schema != LOOKUP_SCHEMA_NAME:
        return None

    # Get row count for referenced table
    ref_table_rows = _get_table_row_count(tables, ref_table)

    # Identify key-value columns in the referenced table
    ref_columns = columns_by_table.get(ref_table, [])
    key_column, value_column = pick_lookup_columns(ref_columns, table_name=ref_table)
    if ref_column and any(col.get(FIELD_COLUMN_NAME) == ref_column for col in ref_columns):
        key_column = ref_column
    if not key_column or not value_column:
        print(f"  Skipping lookup metadata for {ref_table}: could not identify key/value columns")
        return None
    # DEBUG: Uncomment to troubleshoot column selection
    # col_names = [c.get('column_name') for c in ref_columns]
    # print(f"  DEBUG: {ref_table} has columns {col_names}, picked key={key_column}, value={value_column}")

    # Load data from CSV
    csv_path = exports_dir / ref_schema / f"{ref_table}{CSV_EXTENSION}"
    if not csv_path.exists():
        print(f"  Skipping lookup metadata for {ref_table}: CSV not found at {csv_path}")
        return None

    # Generate metadata based on strategy
    if lookup_strategy == "full":
        # Full strategy: embed complete value map, or samples if too large
        value_map = load_value_map(csv_path, key_column, value_column, threshold)

        if value_map is None:
            # Too large for full map - fall back to samples
            samples = load_sample_values(csv_path, key_column, value_column, sample_size=5)
            if not samples:
                print(f"  Skipping lookup metadata for {ref_table}: no samples loaded")
                return None

            # Convert samples list to dictionary format
            value_map_partial = {s["key"]: s["value"] for s in samples}
            print(f"  Generated partial value_map for {ref_table}: {ref_table_rows} rows (showing {len(value_map_partial)} samples)")
            return {
                "value_map_partial": value_map_partial,
                "value_map_source": {
                    FIELD_SCHEMA: ref_schema,
                    "table": ref_table,
                    "key_column": key_column,
                    "value_column": value_column,
                    "row_count": ref_table_rows,
                    "is_partial": True,
                }
            }

        print(f"  Generated full value_map for {ref_table}: {len(value_map)} entries")
        return {
            "value_map": value_map,
            "value_map_source": {
                FIELD_SCHEMA: ref_schema,
                "table": ref_table,
                "key_column": key_column,
                "value_column": value_column,
            }
        }

    elif lookup_strategy == "lightweight":
        # Lightweight strategy: embed row count and sample values
        samples = load_sample_values(csv_path, key_column, value_column, sample_size=5)
        if not samples:
            print(f"  Skipping lookup metadata for {ref_table}: no samples loaded")
            return None

        print(f"  Generated lightweight lookup_info for {ref_table}: {ref_table_rows} rows, {len(samples)} samples")
        return {
            "lookup_info": {
                FIELD_SCHEMA: ref_schema,
                "table": ref_table,
                "key_column": key_column,
                "value_column": value_column,
                "row_count": ref_table_rows,
                "sample_values": samples,
            }
        }

    return None


def _build_column_metadata(
    column: dict[str, Any],
    table_name: str,
    column_comments: dict[Tuple[str, str], str],
    foreign_keys: list[dict[str, Any]],
    tables: dict[str, list[dict[str, Any]]],
    columns_by_table: dict[str, list[dict[str, Any]]],
    exports_dir: Path,
    threshold: int,
    lookup_strategy: str
) -> dict[str, Any]:
    """
    Build metadata dictionary for a single column.

    Args:
        column: Column metadata from database.
        table_name: Name of the table containing this column.
        column_comments: dictionary of column comments.
        foreign_keys: list of foreign key definitions for the table.
        tables: dictionary of table metadata.
        columns_by_table: dictionary of columns indexed by table name.
        exports_dir: Base directory for exported CSV files.
        threshold: Maximum table size for value map inclusion.
        lookup_strategy: Strategy to use for lookup metadata ('full', 'lightweight', or 'none').

    Returns:
        dictionary containing column metadata.
    """
    column_name = column[FIELD_COLUMN_NAME]
    column_metadata = {
        "name": column_name,
        "type": build_type_string(column),
        FIELD_NULLABLE: column.get(FIELD_NULLABLE) == NULLABLE_YES,
    }

    # Only add description if non-empty
    description = column_comments.get((table_name, column_name)) or ""
    if description:
        column_metadata["description"] = description

    # Check if this column is part of a foreign key
    for foreign_key in foreign_keys:
        if column_name in foreign_key[FIELD_COLUMNS]:
            column_index = foreign_key[FIELD_COLUMNS].index(column_name)
            column_metadata[FIELD_REFERENCES] = {
                FIELD_SCHEMA: foreign_key[FIELD_REFERENCES][FIELD_SCHEMA],
                "table": foreign_key[FIELD_REFERENCES]["table"],
                "column": foreign_key[FIELD_REFERENCES][FIELD_COLUMNS][column_index],
            }

            # Try to generate lookup metadata for this foreign key
            ref_column = foreign_key[FIELD_REFERENCES][FIELD_COLUMNS][column_index]
            lookup_metadata = _generate_lookup_metadata_for_column(
                foreign_key,
                tables,
                columns_by_table,
                exports_dir,
                threshold,
                lookup_strategy,
                ref_column=ref_column,
            )
            if lookup_metadata:
                column_metadata.update(lookup_metadata)
            break

    return column_metadata


def generate_table_cards(metadata: dict[str, Any], exports_dir: Path, cards_dir: Path, threshold: int, overwrite: bool, lowercase: bool, lookup_strategy: str):
    """
    Generate table card JSON files from metadata.

    Args:
        metadata: Metadata dictionary containing tables, columns, constraints, etc.
        exports_dir: Base directory containing exported CSV files.
        cards_dir: Output directory for generated table card JSON files.
        threshold: Maximum lookup table size for value map embedding.
        overwrite: Whether to overwrite existing table card files.
        lowercase: Whether to use lowercase filenames.
        lookup_strategy: Strategy for lookup metadata ('full', 'lightweight', or 'none').
    """
    schema_name = metadata[FIELD_SCHEMA]

    # Index metadata by table name
    tables = group_by_key(metadata.get("tables", []), FIELD_TABLE_NAME)
    columns_by_table = group_by_key(metadata.get("columns", []), FIELD_TABLE_NAME)

    # Load ICSR_LOOKUP metadata if we're processing a different schema
    # This is needed to get row counts and column info for lookup tables
    if schema_name != LOOKUP_SCHEMA_NAME:
        lookup_metadata_path = exports_dir / LOOKUP_SCHEMA_NAME / METADATA_FILENAME
        if lookup_metadata_path.exists():
            lookup_metadata = load_metadata(lookup_metadata_path)
            # Merge lookup tables and columns into our dictionaries
            lookup_tables = group_by_key(lookup_metadata.get("tables", []), FIELD_TABLE_NAME)
            lookup_columns = group_by_key(lookup_metadata.get("columns", []), FIELD_TABLE_NAME)
            tables.update(lookup_tables)
            columns_by_table.update(lookup_columns)
    constraints_by_table = group_by_key(metadata.get("constraints", []), FIELD_TABLE_NAME)

    # Build lookup dictionaries for comments
    table_comments = {
        row[FIELD_TABLE_NAME]: row.get(FIELD_COMMENTS)
        for row in metadata.get("table_comments", [])
    }
    column_comments = {
        (row[FIELD_TABLE_NAME], row[FIELD_COLUMN_NAME]): row.get(FIELD_COMMENTS)
        for row in metadata.get("column_comments", [])
    }

    # Build constraint and foreign key structures
    constraint_columns = group_by_key(metadata.get("constraint_columns", []), FIELD_CONSTRAINT_NAME, sort_key=FIELD_POSITION)
    foreign_keys_by_table = build_foreign_keys(metadata.get("foreign_keys", []))

    cards_dir.mkdir(parents=True, exist_ok=True)

    # Generate table cards
    for table_name, columns in columns_by_table.items():
        columns.sort(key=lambda col: col.get(FIELD_COLUMN_ID) or 0)

        # Extract primary key columns
        table_constraints = constraints_by_table.get(table_name, [])
        primary_key_columns = _extract_primary_key_columns(
            table_constraints,
            constraint_columns
        )

        # Get foreign keys for this table
        table_foreign_keys = foreign_keys_by_table.get(table_name, [])

        # Build table card structure
        table_metadata = {
            "schema_name": schema_name,
            "name": table_name,
            "primary_key": primary_key_columns,
            "row_count": _get_table_row_count(tables, table_name),
        }

        # Only add table description if non-empty
        table_description = table_comments.get(table_name) or ""
        if table_description:
            table_metadata["description"] = table_description

        table_card = {
            "table_metadata": table_metadata,
            FIELD_COLUMNS: [],
        }

        # Build metadata for each column
        for column in columns:
            column_metadata = _build_column_metadata(
                column,
                table_name,
                column_comments,
                table_foreign_keys,
                tables,
                columns_by_table,
                exports_dir,
                threshold,
                lookup_strategy
            )
            table_card[FIELD_COLUMNS].append(column_metadata)

        # Write table card to file
        filename = f"{table_name}{JSON_EXTENSION}"
        if lowercase:
            filename = filename.lower()
        output_path = cards_dir / filename

        if output_path.exists() and not overwrite:
            continue

        with output_path.open("w", encoding=UTF8_ENCODING) as handle:
            json.dump(table_card, handle, indent=2)


def main():
    """
    Main entry point for table card generation.

    Parses command line arguments, loads metadata files, and generates table cards
    for each schema found in the metadata.
    """
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
        metadata_paths = sorted(exports_dir.glob(f"*/*{METADATA_FILENAME}"))
        if not metadata_paths:
            raise ValueError("No metadata files found. Provide --schema or --metadata-file.")

    # Process each metadata file
    for metadata_path in metadata_paths:
        metadata = load_metadata(metadata_path)
        schema_name = metadata[FIELD_SCHEMA]
        schema_cards_dir = cards_dir / schema_name

        generate_table_cards(
            metadata,
            exports_dir,
            schema_cards_dir,
            threshold=args.value_map_threshold,
            overwrite=args.overwrite,
            lowercase=args.lowercase_filenames,
            lookup_strategy=args.lookup_strategy,
        )


if __name__ == "__main__":
    main()
