from pathlib import Path


def list_table_cards(table_cards_dir: Path) -> dict[str, list[str]]:
    """
    Gather all table names organized by schema.

    Args:
        table_cards_dir: Path to the table_cards directory

    Returns:
        Dictionary mapping schema names to list of table names
    """
    schemas = {}

    for schema_dir in sorted(table_cards_dir.iterdir()):
        if schema_dir.is_dir():
            schema_name = schema_dir.name
            tables = [f.stem for f in sorted(schema_dir.glob("*.json"))]
            schemas[schema_name] = tables

    return schemas


def print_table_cards(schemas: dict[str, list[str]]) -> None:
    """
    Print table cards in a readable format.

    Args:
        schemas: Dictionary mapping schema names to list of table names
    """
    total_tables = 0

    print("TABLE CARDS INVENTORY")
    for schema_name, tables in schemas.items():
        table_count = len(tables)
        total_tables += table_count

        print(f"\n[{schema_name}] ({table_count} tables)")
        print("-" * 55)

        for table in tables:
            print(f"   - {table}")

    print(f"\n SUMMARY: {len(schemas)} schemas, {total_tables} table cards")


def main():
    root = Path(__file__).resolve().parent.parent.parent
    table_cards_dir = root / "input" / "table_cards"

    if not table_cards_dir.exists():
        print(f"Error: Table cards directory not found: {table_cards_dir}")
        return

    schemas = list_table_cards(table_cards_dir)
    print_table_cards(schemas)


if __name__ == "__main__":
    main()
