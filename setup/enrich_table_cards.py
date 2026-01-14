import json
import logging
import argparse

import pandas as pd

from pathlib import Path
from typing import Any, Optional 

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

# Resolve project root relative to this script: setup/enrich_table_cards.py -> ../ -> Project Root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXPORTS_DIR = PROJECT_ROOT / "input/supplied_descriptions"
# all schemas (ICSR, ICSR_LOOKUP, ICSR_EMA, etc.) get enriched in one pass
DEFAULT_CARDS_DIR = PROJECT_ROOT / "input/table_cards"
TABLE_EXCEL_FILE = "ev-icsr-tables.xlsx"
COLUMN_EXCEL_FILE = "ev-icsr-columns.xlsx"


def clean_text(text: Any) -> Optional[str]:
    """
    Clean text by removing Excel artifacts and extra whitespace.

    Args:
        text: The raw text input (can be None, float(nan), or string).

    Returns:
        Cleaned string or None if the input is empty/invalid.
    """
    if pd.isna(text) or text is None:
        return None

    text_str = str(text).strip()
    if text_str.lower() == "nan":
        return None
    
    # Remove specific Excel artifact
    text_str = text_str.replace("_x000D_", "\n")
    
    # Normalize newlines and strip again
    text_str = text_str.strip()
    
    return text_str if text_str else None


def load_excel_data(exports_dir: Path) -> tuple[dict[tuple[str, str], str], dict[str, dict[str, str]]]:
    """
    Load table and column descriptions from Excel files.

    Args:
        exports_dir: Directory containing the Excel files.

    Returns:
        A tuple containing:
        - table_map: dict[(owner/schema, table_name), description]
        - column_map: dict[table_name, dict[column_name, description]]
    """
    table_path = exports_dir / TABLE_EXCEL_FILE
    column_path = exports_dir / COLUMN_EXCEL_FILE

    if not table_path.exists() or not column_path.exists():
        raise FileNotFoundError(f"Excel files not found in {exports_dir}")

    logger.info(f"Loading Excel data from {exports_dir}...")

    # Load tables
    # Expected columns: 'Name' (Table Name), 'Comment' (Description), 'Owner' (schema)
    df_tables = pd.read_excel(table_path)
    table_map = {}
    for _, row in df_tables.iterrows():
        table_name = str(row.get('Name', '')).strip().upper()
        owner = clean_text(row.get('Owner'))
        owner = owner.upper() if owner else None
        description = clean_text(row.get('Comment'))
        if table_name and description:
            key = (owner, table_name)
            table_map[key] = description

    # Load columns
    # Expected columns: 'Table', 'Name' (Column Name), 'Comment'
    df_columns = pd.read_excel(column_path)
    column_map = {}
    for _, row in df_columns.iterrows():
        table_name = str(row.get('Table', '')).strip().upper()
        col_name = str(row.get('Name', '')).strip().upper()
        description = clean_text(row.get('Comment'))

        if table_name and col_name and description:
            if table_name not in column_map:
                column_map[table_name] = {}
            column_map[table_name][col_name] = description

    logger.info(f"Loaded descriptions for {len(table_map)} tables and {sum(len(c) for c in column_map.values())} columns.")
    return table_map, column_map


def process_card(
    file_path: Path,
    table_descriptions: dict[tuple[str, str], str],
    column_descriptions: dict[str, dict[str, str]]
) -> bool:
    """
    Process a single JSON card file, updating it if descriptions are missing.

    Args:
        file_path: Path to the JSON card file.
        table_descriptions: dictionary of table descriptions from Excel.
        column_descriptions: Nested dictionary of column descriptions from Excel.

    Returns:
        True if the file was modified, False otherwise.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to read {file_path}: {e}")
        return False

    is_modified = False
    
    # Update table description
    table_meta = data.get('table_metadata', {})
    table_name = table_meta.get('name', '').upper()
    schema_name = table_meta.get('schema_name', '') or file_path.parent.name
    schema_name = str(schema_name).upper()
    current_table_desc = table_meta.get('description')

    if not current_table_desc:
        new_desc = table_descriptions.get((schema_name, table_name)) or table_descriptions.get((None, table_name))
        if new_desc:
            table_meta['description'] = new_desc
            is_modified = True
            logger.debug(f"[{table_name}] Added table description.")

    # Update column descriptions
    columns = data.get('columns', [])
    if table_name in column_descriptions:
        excel_cols = column_descriptions[table_name]
        
        for col in columns:
            col_name = col.get('name', '').upper()
            current_col_desc = col.get('description')

            if not current_col_desc:
                new_col_desc = excel_cols.get(col_name)
                if new_col_desc:
                    col['description'] = new_col_desc
                    is_modified = True
                    logger.debug(f"[{table_name}.{col_name}] Added column description.")

    # Save if modified
    if is_modified:
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to write {file_path}: {e}")
            return False

    return False


def main():
    parser = argparse.ArgumentParser(description="Enrich table cards with Excel descriptions.")
    parser.add_argument("--exports-dir", type=Path, default=DEFAULT_EXPORTS_DIR, help="Directory containing Excel exports.")
    parser.add_argument(
        "--cards-dir",
        type=Path,
        default=DEFAULT_CARDS_DIR,
        help="Directory containing JSON table cards. Can be the root (e.g., input/table_cards) or a single schema directory.",
    )
    args = parser.parse_args()

    # Log the paths being used for debugging
    logger.info(f"Using exports directory: {args.exports_dir}")
    logger.info(f"Using cards directory: {args.cards_dir}")

    if not args.exports_dir.exists():
        logger.error(f"Exports directory does not exist: {args.exports_dir}")
        return

    if not args.cards_dir.exists():
        logger.error(f"Cards directory does not exist: {args.cards_dir}")
        return
    if not args.cards_dir.is_dir():
        logger.error(f"Cards path is not a directory: {args.cards_dir}")
        return

    try:
        table_descs, column_descs = load_excel_data(args.exports_dir)
    except Exception as e:
        logger.error(f"Error loading Excel data: {e}")
        return

    # Allow pointing to root (input/table_cards) or a single schema directory
    has_subdirs = any(p.is_dir() for p in args.cards_dir.iterdir())
    json_files = list(args.cards_dir.rglob("*.json") if has_subdirs else args.cards_dir.glob("*.json"))
    logger.info(f"Found {len(json_files)} JSON card files to process.")

    modified_count = 0
    for card_file in json_files:
        if process_card(card_file, table_descs, column_descs):
            modified_count += 1
            logger.info(f"Updated {card_file.name}")

    logger.info(f"Processing complete. {modified_count} files updated.")


if __name__ == "__main__":
    main()
