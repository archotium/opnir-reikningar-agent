"""Read-only access to the invoice database, safe to hand to a language model.

The model writes the SQL, so nothing it writes may change data, read other
files, or run for ever. Four independent layers, so no single mistake is
enough:

1. The file is opened read-only (mode=ro): SQLite itself refuses writes.
2. An authorizer approves every action while a statement is compiled and
   allows only reading tables and calling functions. INSERT, UPDATE, DELETE,
   DROP, CREATE, ATTACH and PRAGMA are refused before anything runs. This
   checks what the statement *does*, not what the text looks like, so tricks
   like comments or odd capitalisation don't get round it.
3. One statement per call (Python's sqlite3 refuses several), and each query
   is stopped after QUERY_TIMEOUT seconds.
4. At most MAX_ROWS rows go back to the model.

Privacy: suppliers who are individual people (privacy.py decides who) are hidden at the
source, not in the output. On each connection a temporary view named `vendor` shadows the
real table and shows their names as privacy.MASK, and `line_flat` is rebuilt on top of it.
The authorizer refuses any read of the real vendor.name except through that view, so no
query (main.vendor, substr(name, ...), WHERE name = 'Jón Jónsson') can see or match a
person's name. Their payments still count in every total.
"""

import difflib
import sqlite3
import time

from . import privacy
from .config import DB_PATH

MAX_ROWS = 200
QUERY_TIMEOUT = 10.0  # seconds

_ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ,
                    sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}

NAME_TABLES = ("buyer", "vendor", "cost_type")


class QueryError(Exception):
    """A query was refused or failed; the message is safe to show the model."""


def _authorizer(action, arg1, arg2, db_name, view):
    if action == sqlite3.SQLITE_READ and (db_name, arg1, arg2) == ("main", "vendor", "name"):
        # the real names only through the masking view (view = innermost view being read)
        return sqlite3.SQLITE_OK if view == "vendor" else sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


def _mask_people(con: sqlite3.Connection) -> None:
    """Shadow vendor and line_flat with temporary views that hide people's names.
    Temporary objects live in memory, so this works on the read-only file."""
    people = privacy.people([n for (n,) in con.execute("SELECT name FROM vendor")])
    con.create_function("mask_person", 1,
                        lambda s: privacy.MASK if s in people else s, deterministic=True)
    flat = con.execute("SELECT sql FROM sqlite_master WHERE name = 'line_flat'").fetchone()[0]
    con.execute("CREATE TEMP VIEW vendor AS SELECT id, mask_person(name) AS name FROM main.vendor")
    con.execute(flat.replace("CREATE VIEW", "CREATE TEMP VIEW", 1))


def connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise SystemExit(f"{DB_PATH} not found; run scripts/download.py and scripts/build_db.py")
    con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True,
                          check_same_thread=False)
    # fold(x): lower-case that also handles Icelandic letters (SQLite's own
    # LOWER and LIKE only fold A-Z), for case-insensitive name matching.
    con.create_function("fold", 1, lambda s: s.casefold() if isinstance(s, str) else s,
                        deterministic=True)
    _mask_people(con)  # before the authorizer, which forbids creating views
    con.set_authorizer(_authorizer)
    return con


def run_query(con: sqlite3.Connection, sql: str) -> dict:
    """Run one read-only SELECT and return columns, rows and whether rows were cut off."""
    deadline = time.monotonic() + QUERY_TIMEOUT
    con.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    try:
        cur = con.execute(sql)
        if cur.description is None:
            raise QueryError("only SELECT queries are allowed")
        rows = cur.fetchmany(MAX_ROWS + 1)
    except sqlite3.DatabaseError as e:  # includes ProgrammingError (several statements)
        msg = str(e)
        if "not authorized" in msg:
            msg = "not allowed: the database is read-only and only SELECT is permitted"
        elif "vendor.name is prohibited" in msg:
            msg = (f"not allowed: names of individual people are hidden; read supplier names "
                   f"from vendor or line_flat, where people show as {privacy.MASK}")
        elif "interrupted" in msg:
            msg = f"query stopped after {QUERY_TIMEOUT:.0f} s; aggregate more or filter first"
        raise QueryError(msg) from None
    finally:
        con.set_progress_handler(None, 0)
    return {
        "columns": [d[0] for d in cur.description],
        "rows": [list(r) for r in rows[:MAX_ROWS]],
        "truncated": len(rows) > MAX_ROWS,
    }


def find_names(con: sqlite3.Connection, table: str, text: str, limit: int = 15) -> list[str]:
    """Exact names in buyer/vendor/cost_type that match a partial or misspelt name.

    First every name containing the text (ignoring case, Icelandic letters
    included); if none, the closest spellings.
    """
    if table not in NAME_TABLES:
        raise QueryError(f"table must be one of {', '.join(NAME_TABLES)}")
    names = list(dict.fromkeys(n for (n,) in con.execute(f"SELECT name FROM {table}")))
    needle = text.casefold().strip()
    hits = [n for n in names if needle in n.casefold()]
    if not hits:
        folded = {n.casefold(): n for n in names}
        hits = [folded[m] for m in difflib.get_close_matches(needle, folded, n=limit, cutoff=0.6)]
    return sorted(hits, key=len)[:limit]


def schema_text(con: sqlite3.Connection) -> str:
    """The CREATE statements of the tables and the view, for the model's instructions."""
    rows = con.execute("SELECT sql FROM sqlite_master WHERE type IN ('table', 'view') "
                       "AND name != 'load_log' ORDER BY type, name").fetchall()
    return "\n\n".join(sql for (sql,) in rows)
