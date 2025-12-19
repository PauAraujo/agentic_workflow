import sqlite3

import pandas as pd

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = ROOT / "input" / "db_exports" / "PATIENT_202512051327.csv"
DB_PATH = ROOT / "input" / "db" / "patients.db"
TABLE_NAME = "PATIENT"


def _load_source(path: Path) -> pd.DataFrame:
    """
    Load either CSV or Excel into a DataFrame based on file extension.

    Args:
        path: Path to the source file (CSV or Excel)

    """
    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(path)
    raise ValueError(f"Unsupported source format: {suffix} (expected .csv or .xlsx)")


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    df = _load_source(SOURCE_PATH)

    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    try:
        # Write Excel/CSV rows into SQLite
        df.to_sql(TABLE_NAME, conn, if_exists="replace", index=False)
    finally:
        conn.close()

    print(f"Created SQLite database at {DB_PATH} with table {TABLE_NAME}")

if __name__ == "__main__":
    main()
