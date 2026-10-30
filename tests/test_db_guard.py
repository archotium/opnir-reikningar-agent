"""The SQL tool must refuse anything that isn't a bounded read.

Runs against the real data/opnir.db, no network. Usage: python -m pytest tests
"""

import pytest

from opnir_agent import db


@pytest.fixture(scope="module")
def con():
    return db.connect()


def test_select_works(con):
    out = db.run_query(con, "SELECT COUNT(*) FROM buyer")
    assert out["columns"] == ["COUNT(*)"]
    assert out["rows"][0][0] > 100
    assert out["truncated"] is False


WRITES = [  # also sent through the MCP server in test_mcp_server.py
    "DELETE FROM buyer",
    "UPDATE buyer SET name = 'x'",
    "INSERT INTO buyer (name) VALUES ('x')",
    "DROP TABLE buyer",
    "CREATE TABLE t (x)",
    "ATTACH DATABASE 'other.db' AS other",
    "PRAGMA writable_schema = ON",
    "PRAGMA table_info(buyer)",
    "  delete /* hidden */ FROM buyer",
    "WITH x AS (SELECT 1) DELETE FROM buyer",
    "SELECT load_extension('evil')",
    "SELECT 1; DELETE FROM buyer",
]


@pytest.mark.parametrize("sql", WRITES)
def test_writes_and_side_effects_refused(con, sql):
    with pytest.raises(db.QueryError):
        db.run_query(con, sql)
    assert db.run_query(con, "SELECT COUNT(*) FROM buyer")["rows"][0][0] > 100


def test_two_statements_refused(con):
    with pytest.raises(db.QueryError):
        db.run_query(con, "SELECT 1; DELETE FROM buyer")


def test_rows_capped(con):
    out = db.run_query(con, "SELECT id FROM invoice")
    assert len(out["rows"]) == db.MAX_ROWS
    assert out["truncated"] is True


def test_runaway_query_stopped(con, monkeypatch):
    monkeypatch.setattr(db, "QUERY_TIMEOUT", 0.5)
    with pytest.raises(db.QueryError, match="stopped"):
        db.run_query(con, "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) "
                          "SELECT COUNT(*) FROM n")


def test_fold_handles_icelandic(con):
    out = db.run_query(con, "SELECT name FROM buyer WHERE fold(name) = fold('VEÐURSTOFA ÍSLANDS')")
    assert out["rows"] == [["Veðurstofa Íslands"]]


def test_find_names_partial_and_misspelt(con):
    assert "Veðurstofa Íslands" in db.find_names(con, "buyer", "veðurstof")
    assert "Landspítali" in db.find_names(con, "buyer", "Landspitali")  # no accent
    with pytest.raises(db.QueryError):
        db.find_names(con, "sqlite_master", "x")
