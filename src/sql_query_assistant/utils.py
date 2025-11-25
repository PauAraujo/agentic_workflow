import yaml
import json

from pathlib import Path

from sql_query_assistant.constants import ASSUMPTIONS_CATALOG_FILE, TABLE_CARDS_DIR
from sql_query_assistant.domain import AssumptionCatalogEntry, TableCard


def load_table_cards(base_path: Path = TABLE_CARDS_DIR) -> list[TableCard]:
    """
    Load all table cards from the specified directory.

    Args:
        base_path: Path to the directory containing table card JSON files

    Returns:
        list of validated TableCard models
    """
    table_cards: list[TableCard] = []
    for json_file in sorted(base_path.glob("*.json")):
        data = json.loads(json_file.read_text())
        table_cards.append(TableCard.model_validate(data))

    return table_cards


def load_assumption_catalog(
    catalog_path: Path = ASSUMPTIONS_CATALOG_FILE,
) -> list[AssumptionCatalogEntry]:
    """
    Load the assumptions catalog from YAML file.

    Args:
        catalog_path: Path to the assumptions catalog YAML file

    Returns:
        Assumption catalog as a list of validated models
    """
    raw_catalog = yaml.safe_load(catalog_path.read_text()) or []
    return [AssumptionCatalogEntry.model_validate(entry) for entry in raw_catalog]
