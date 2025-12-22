import sys
import sqlite3

import pandas as pd

from pathlib import Path

from sql_query_assistant.config import Settings

sys.path.append(str(Path(__file__).parents[2]))


def build_schema(
    schema_name: str,
    source_file: Path,
    settings: Settings,
    reset_db: bool = True,
):
    """Creates or updates a specific schema database from a source file."""

    # The filename becomes the schema name (e.g., input/db/ICSR.db)
    db_path = settings.paths.db_dir / f"{schema_name}.db"

    # Load data
    print(f"Loading data from {source_file}...")
    if source_file.suffix == '.csv':
        df = pd.read_csv(source_file)
    elif source_file.suffix in ('.xlsx', '.xls'):
        df = pd.read_excel(source_file)
    else:
        raise ValueError(f"Unknown format: {source_file}")

    # Create DB
    settings.paths.db_dir.mkdir(parents=True, exist_ok=True)

    # Remove old DB if requested to ensure clean slate
    if reset_db and db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    try:
        # Use the filename as the table name
        table_name = source_file.stem.split('_')[0] # e.g. PATIENT_2025 -> PATIENT

        df.to_sql(table_name, conn, index=False)
        print(f"✅ Created schema '{schema_name}' at {db_path} (Table: {table_name})")
    finally:
        conn.close()

def main():
    settings = Settings()

    export_dir = settings.paths.input_dir / "db_exports"
    if not export_dir.exists():
        raise FileNotFoundError(f"Export directory not found: {export_dir}")

    schema_dirs = [path for path in sorted(export_dir.iterdir()) if path.is_dir()]
    if not schema_dirs:
        print(f"No schema folders found in {export_dir}")
        return

    for schema_dir in schema_dirs:
        csv_files = [
            path for path in sorted(schema_dir.iterdir())
            if path.is_file() and path.suffix.lower() == ".csv"
        ]
        if not csv_files:
            print(f"No CSV files found in {schema_dir}")
            continue

        for index, source_path in enumerate(csv_files):
            build_schema(
                schema_dir.name,
                source_path,
                settings,
                reset_db=(index == 0),
            )

if __name__ == "__main__":
    main()
