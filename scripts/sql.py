"""Run SQL against data/opnir.db and print the result as a table.

The database is opened read-only, so a mistyped DELETE or UPDATE fails
instead of changing data. A file can hold several statements separated by
semicolons; each result is printed in turn.

Usage:
  python scripts/sql.py "SELECT COUNT(*) FROM buyer"
  python scripts/sql.py practice/my_answers.sql
"""

import sqlite3
import sys
import time
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "opnir.db"
MAX_ROWS = 50


def print_table(cur: sqlite3.Cursor) -> None:
    headers = [d[0] for d in cur.description]
    rows = cur.fetchmany(MAX_ROWS + 1)
    more = len(rows) > MAX_ROWS
    rows = [[f"{v:,}" if isinstance(v, int) and not isinstance(v, bool) else str(v)
             for v in r] for r in rows[:MAX_ROWS]]
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h)
              for i, h in enumerate(headers)]
    print(" | ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("-+-".join("-" * w for w in widths))
    for r in rows:
        print(" | ".join(v.ljust(w) for v, w in zip(r, widths)))
    print(f"({len(rows)} rows{', more not shown' if more else ''})")


def split_statements(text: str) -> list[str]:
    """Split on statement ends, leaving semicolons inside comments and strings alone."""
    statements, buffer = [], ""
    for line in text.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        statements.append(buffer.strip())  # last statement without a semicolon
    # drop chunks that are only comments
    return [s for s in statements
            if any(l.strip() and not l.strip().startswith("--") for l in s.splitlines())]


def main(arg: str) -> None:
    path = Path(arg)
    text = path.read_text(encoding="utf-8") if path.suffix == ".sql" and path.exists() else arg
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    for stmt in split_statements(text):
        print(f"\n{stmt}\n")
        start = time.perf_counter()
        try:
            cur = con.execute(stmt)
        except sqlite3.Error as e:
            print(f"ERROR: {e}")
            continue
        if cur.description:
            print_table(cur)
        print(f"[{time.perf_counter() - start:.2f} s]")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
