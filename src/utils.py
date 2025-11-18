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

    # Load individual table card files
    patient = json.loads((base / "patient.json").read_text())
    patient_age_group = json.loads((base / "patient_age_group.json").read_text())
    patient_sex = json.loads((base / "patient_sex.json").read_text())

    # Extract table_card from each
    return [
        patient["table_card"],
        patient_age_group["table_card"],
        patient_sex["table_card"],
    ]


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