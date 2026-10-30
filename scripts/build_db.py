"""Build data/opnir.db from the monthly exports in data/raw/.

Reads every YYYY-MM.xlsx, checks the columns are the ones expected, splits
the flat rows into the tables in sql/schema.sql and records each file's row
count in load_log. The database is rebuilt from scratch every run.

Usage: python scripts/build_db.py
"""

import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DB = ROOT / "data" / "opnir.db"
SCHEMA = ROOT / "sql" / "schema.sql"

# Export header, in order -> our column name
COLUMNS = {
    "Kaupandi": "buyer",
    "Dags.greiðslu": "payment_date",
    "Birgi": "vendor",
    "Tegund": "cost_type",
    "Númer reiknings": "invoice_number",
    "Upphæð línu": "amount",
}


# Names the source system serves with broken characters (U+FFFD in place of
# Icelandic letters; the website shows them the same way). Repaired here so
# a search for the real name finds them. See DATA_NOTES.md.
REPAIRS = {
    "Menntasj��ur n�msmanna": "Menntasjóður námsmanna",
    "Ranns�knarstofur, �n VSK": "Rannsóknarstofur, án VSK",
    "V�rsluf�, -sj��ir": "Vörslufé, -sjóðir",
}


def read_month(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, engine="calamine", dtype={"Númer reiknings": str})
    if list(df.columns) != list(COLUMNS):
        raise ValueError(f"{path.name}: unexpected columns {list(df.columns)}")
    df = df.rename(columns=COLUMNS)
    if df.isna().any().any():
        raise ValueError(f"{path.name}: empty cells in {df.columns[df.isna().any()].tolist()}")
    df["payment_date"] = pd.to_datetime(df["payment_date"]).dt.strftime("%Y-%m-%d")
    for col in ("buyer", "vendor", "cost_type", "invoice_number"):
        df[col] = df[col].str.strip()
    for col in ("buyer", "vendor", "cost_type"):
        df[col] = df[col].replace(REPAIRS)
    df["source_file"] = path.name
    return df


def lookup(con: sqlite3.Connection, table: str, names: pd.Series) -> pd.Series:
    """Insert the distinct names into a lookup table, return the id for every row."""
    unique = sorted(names.unique())
    con.executemany(f"INSERT INTO {table} (id, name) VALUES (?, ?)",
                    list(enumerate(unique, start=1)))
    return names.map({n: i for i, n in enumerate(unique, start=1)})


def main() -> None:
    files = sorted(RAW.glob("????-??.xlsx"))
    if not files:
        raise SystemExit(f"no exports in {RAW}; run scripts/download.py first")
    df = pd.concat([read_month(f) for f in files], ignore_index=True)

    DB.unlink(missing_ok=True)
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.execute("CREATE TABLE load_log (source_file TEXT PRIMARY KEY, rows INTEGER NOT NULL)")
    con.executemany("INSERT INTO load_log VALUES (?, ?)",
                    df.groupby("source_file").size().items())

    df["buyer_id"] = lookup(con, "buyer", df["buyer"])
    df["vendor_id"] = lookup(con, "vendor", df["vendor"])
    df["cost_type_id"] = lookup(con, "cost_type", df["cost_type"])

    key = ["buyer_id", "vendor_id", "invoice_number", "payment_date"]
    invoices = df[key].drop_duplicates().reset_index(drop=True)
    invoices["id"] = invoices.index + 1
    con.executemany(
        "INSERT INTO invoice (id, buyer_id, vendor_id, invoice_number, payment_date) "
        "VALUES (?, ?, ?, ?, ?)",
        invoices[["id", *key]].itertuples(index=False, name=None))

    df = df.merge(invoices, on=key, how="left", validate="many_to_one")
    con.executemany(
        "INSERT INTO invoice_line (invoice_id, cost_type_id, amount) VALUES (?, ?, ?)",
        df[["id", "cost_type_id", "amount"]].astype(int).itertuples(index=False, name=None))

    con.commit()
    con.execute("VACUUM")
    con.close()
    print(f"{DB.name}: {len(df):,} lines, {len(invoices):,} invoices from {len(files)} files")


if __name__ == "__main__":
    main()
