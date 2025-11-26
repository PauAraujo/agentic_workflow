import json
import yaml

from pathlib import Path

from sql_query_assistant.config import Settings
from sql_query_assistant.domain import AssumptionCatalogEntry, TableCard


def load_table_cards(
    settings: Settings,
    base_path: Path | None = None,
) -> list[TableCard]:
    """
    Load all table cards from the specified directory.

    If base_path is not provided, uses the configured table_cards_dir.

    Args:
        base_path: Path to the directory containing table card JSON files.
                   If None, uses the default from PathSettings.
        settings: Settings instance to use for path resolution.

    Returns:
        list of validated TableCard models
    """
    if base_path is None:
        base_path = settings.paths.table_cards_dir

    table_cards: list[TableCard] = []
    for json_file in sorted(base_path.glob("*.json")):
        data = json.loads(json_file.read_text())
        table_cards.append(TableCard.model_validate(data))

    return table_cards


def load_assumption_catalog(
    settings: Settings,
    catalog_path: Path | None = None,
) -> list[AssumptionCatalogEntry]:
    """
    Load the assumptions catalog from YAML file.

    If catalog_path is not provided, uses the configured assumptions_catalog_file.

    Args:
        catalog_path: Path to the assumptions catalog YAML file.
                      If None, uses the default from PathSettings.
        settings: Settings instance to use for path resolution.

    Returns:
        Assumption catalog as a list of validated models
    """
    if catalog_path is None:
        catalog_path = settings.paths.assumptions_catalog_file

    raw_catalog = yaml.safe_load(catalog_path.read_text()) or []
    return [AssumptionCatalogEntry.model_validate(entry) for entry in raw_catalog]
