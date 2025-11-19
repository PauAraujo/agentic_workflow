import json
import yaml

from typing import Any
from pathlib import Path

from .constants import TABLE_CARDS_DIR, ASSUMPTIONS_CATALOG_FILE

def load_table_cards(base_path: Path = TABLE_CARDS_DIR) -> list[dict[str, Any]]:
    """
    Load all table cards from the specified directory.

    Args:
        base_path: Path to the directory containing table card JSON files

    Returns:
        list of table card dictionaries
    """
    table_cards = []
    for json_file in sorted(base_path.glob("*.json")):
        data = json.loads(json_file.read_text())
        table_cards.append(data)

    return table_cards


def load_assumption_catalog(
    catalog_path: Path = ASSUMPTIONS_CATALOG_FILE
) -> list[dict[str, Any]]:
    """
    Load the assumptions catalog from YAML file.

    Args:
        catalog_path: Path to the assumptions catalog YAML file

    Returns:
        Assumption catalog as a list of dictionaries
    """
    return yaml.safe_load(catalog_path.read_text())