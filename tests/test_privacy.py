"""People's names must not leave the database, by any query; totals must not change.

Runs against the real data/opnir.db, no network. Usage: python -m pytest tests
"""

import pytest

from opnir_agent import db, privacy

PERSON = "Jón Jónsson"  # an individual supplier in the 2025 data; the most common
# name in Iceland, so testing with it singles nobody out. The other names below are
# invented (none is a supplier) and only exercise the rule.
COMPANY = "Advania Ísland ehf."


@pytest.fixture(scope="module")
def con():
    return db.connect()


@pytest.mark.parametrize("name, person", [
    ("Hrefna Kolbrúnardóttir", True),
    ("Fannar Geir Garðarsson", True),       # "garð" is also an organisation word part
    ("Ásgerður Tinna Pálmadóttir", True),  # so is "gerð"
    ("Örvar Beekholt", True),
    ("Marta Brunelli", True),
    ("Pieter Jan de Wilde", True),
    ("Hekla Magnúsd. Vestergaard", True),
    ("Ađalsteinn Tjörvason", True),           # ð garbled as đ at the source
    ("Egill Baldursson ehf.", False),       # a company named after its owner
    ("Lögmannsstofa Ólafs Björnssonar", False),
    ("Björgunarsveitin Garðar", False),
    ("Hitaveita Fjarðabyggðar", False),
    ("Vestmannaeyjaferjan Herjólfur", False),
    ("Alliance Francaise", False),
    ("Veðurstofa Íslands", False),
])
def test_is_person(name, person):
    assert privacy.is_person(name) is person


def test_person_masked_company_not(con):
    rows = db.run_query(con, "SELECT name FROM vendor")["rows"]
    names = {r[0] for r in rows} | {n for (n,) in con.execute("SELECT name FROM vendor")}
    assert PERSON not in names and COMPANY in names
    assert privacy.MASK in names


@pytest.mark.parametrize("sql", [
    f"SELECT COUNT(*) FROM vendor WHERE name = '{PERSON}'",
    f"SELECT COUNT(*) FROM line_flat WHERE vendor = '{PERSON}'",
    "SELECT COUNT(*) FROM vendor WHERE name LIKE 'Jón Jóns%'",
    "SELECT COUNT(*) FROM vendor WHERE fold(name) = fold('JÓN JÓNSSON')",
    "SELECT COUNT(*) FROM vendor WHERE instr(name, 'Jón Jónsson') > 0",
])
def test_lookup_by_name_finds_nothing(con, sql):
    assert db.run_query(con, sql)["rows"] == [[0]]


@pytest.mark.parametrize("sql", [
    "SELECT name FROM main.vendor",
    "SELECT substr(name, 1, 5) FROM main.vendor",
    "SELECT vendor FROM main.line_flat",
    "SELECT COUNT(*) FROM main.vendor WHERE name LIKE 'Jón Jóns%'",
])
def test_real_names_refused(con, sql):
    with pytest.raises(db.QueryError, match="hidden"):
        db.run_query(con, sql)


def test_find_names_hides_people(con):
    assert db.find_names(con, "vendor", "Sigurðardóttir") == []
    assert db.find_names(con, "vendor", "einstakl") == [privacy.MASK]
    assert COMPANY in db.find_names(con, "vendor", "advania")


def test_totals_unchanged(con):
    raw = con.execute("SELECT SUM(amount), COUNT(*) FROM main.invoice_line").fetchone()
    flat = db.run_query(con, "SELECT SUM(amount), COUNT(*) FROM line_flat")["rows"][0]
    assert list(raw) == flat
    people = db.run_query(con, f"SELECT COUNT(*) FROM vendor WHERE name = '{privacy.MASK}'")
    assert 1000 < people["rows"][0][0] < 2000
