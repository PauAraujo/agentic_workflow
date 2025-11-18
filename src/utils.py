import json
import yaml

from pathlib import Path
from typing import Dict, Any, List

def load_table_cards(base_path: str = "input/table_cards") -> List[Dict[str, Any]]:
    """
    Load all table cards from the specified directory.

    Args:
        base_path: Path to the directory containing table card JSON files

    Returns:
        List of table card dictionaries
    """
    base = Path(base_path)

    #  load all JSON files in the directory
    table_cards = []
    for json_file in sorted(base.glob("*.json")):
        data = json.loads(json_file.read_text())
        if "table_card" in data:
            table_cards.append(data["table_card"])

    return table_cards


def load_assumption_catalog(
    catalog_path: str = "input/assumptions_catalog/assumptions_catalog.yaml"
) -> List[Dict[str, Any]]:
    """
    Load the assumptions catalog from YAML file.

    Args:
        catalog_path: Path to the assumptions catalog YAML file

    Returns:
        Assumption catalog as a list of dictionaries
    """
    return yaml.safe_load(Path(catalog_path).read_text())