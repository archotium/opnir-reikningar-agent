"""Check data/opnir.db against itself and against opnirreikningar.is.

1. Row counts: every monthly file in the database has the number of lines
   the website says that month's export contains.
2. Integrity: no orphan ids, no duplicate invoices, invoice numbers kept as text.
3. Spot checks: for a few (buyer, vendor, month) pairs, the same invoices
   exist on both sides and each invoice's lines match the website (see
   spot_check for invoices paid in instalments).

Needs network access. Usage: python tests/check_db.py
"""

import calendar
import json
import sqlite3
import sys
import urllib.parse
import urllib.request
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "opnir.db"
SITE = "https://opnirreikningar.is"

failures = []


def check(ok: bool, label: str) -> None:
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


def get_json(path: str, params) -> dict:
    url = f"{SITE}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def month_range(ym: str) -> tuple[str, str]:
    year, month = map(int, ym.split("-"))
    last = calendar.monthrange(year, month)[1]
    return f"01.{month:02d}.{year}", f"{last:02d}.{month:02d}.{year}"


def site_ids(kind: str, name: str) -> list[str]:
    """The site's ids for an agency (kind='org') or supplier (kind='vendor').

    One name can have several ids (e.g. an agency re-registered), so all
    exact matches are returned and searched.
    """
    hits = get_json(f"/rest/{kind}", {"term": name})["data"]
    exact = [h["id"] for h in hits if h["text"] == name]
    if not exact:
        raise LookupError(f"{kind} {name!r}: not found on the site")
    return exact


def site_invoices(buyer: str, vendor: str, ym: str) -> dict[str, dict]:
    """Every invoice the website search returns for one month, keyed by unique_id.

    The search serves at most 50 invoices per request and appends one extra
    row when more exist (the site's own page drops it). It sorts on payment
    date, which is not unique, so paging through a long result can repeat
    some rows and skip others. Fetching one day at a time keeps results short.
    """
    year, month = map(int, ym.split("-"))
    days = calendar.monthrange(year, month)[1]
    found, page = {}, 50
    for org_id in site_ids("org", buyer):
        for vendor_id in site_ids("vendor", vendor):
            for day in range(1, days + 1):
                date = f"{day:02d}.{month:02d}.{year}"
                base = {"vendor_id": vendor_id, "type_id": "", "org_id": org_id,
                        "timabil_fra": date, "timabil_til": date,
                        "draw": 1, "order[0][column]": 3, "order[0][dir]": "asc",
                        "search[value]": "", "search[regex]": "false"}
                for i, col in enumerate(["org_name", "check_date", "vendor_name",
                                         "invoice_amount", "check_amount", ""]):
                    base[f"columns[{i}][data]"] = col
                start = 0
                while True:
                    rows = get_json("/data_pagination_search",
                                    {**base, "start": start, "length": page})["data"]
                    found.update((r["unique_id"], r) for r in rows[:page])
                    if len(rows) <= page:
                        break
                    start += page
    return found


def site_line_total(check_id: int, invoice_id: int) -> int:
    """Sum of the lines the website shows for one paid invoice."""
    params = {"check_id": check_id, "invoice_id": invoice_id, "draw": 1,
              "start": 0, "length": 1000, "order[0][column]": 0, "order[0][dir]": "asc",
              "columns[0][data]": "type_name", "columns[1][data]": "line_amount"}
    return sum(int(r["line_amount"]) for r in get_json("/data_pagination_line", params)["data"])


def spot_check(con: sqlite3.Connection, buyer: str, vendor: str, ym: str) -> None:
    """Compare one (buyer, vendor, month) invoice by invoice with the website.

    The database stores the export's lines. For most invoices the lines add
    up to the amount paid. For an invoice paid in instalments the export
    repeats the full invoice lines with each payment, so lines and payment
    differ; such an invoice passes if the site's own lines equal ours.
    """
    db = dict(con.execute("""
        SELECT i.invoice_number, SUM(l.amount)
        FROM invoice_line l JOIN invoice i ON i.id = l.invoice_id
        JOIN buyer b ON b.id = i.buyer_id JOIN vendor v ON v.id = i.vendor_id
        WHERE b.name = ? AND v.name = ? AND substr(i.payment_date, 1, 7) = ?
        GROUP BY i.invoice_number""", (buyer, vendor, ym)).fetchall())
    site = site_invoices(buyer, vendor, ym)
    paid = {}
    for r in site.values():
        paid.setdefault(r["invoice_num"], []).append(r)

    label = f"{ym} {buyer} / {vendor}"
    check(set(db) == set(paid), f"{label}: same {len(db):,} invoices on both sides "
          f"(site {len(paid):,})")
    partial = []
    for number in set(db) & set(paid):
        site_paid = sum(int(r["invoice_amount"]) for r in paid[number])
        if db[number] == site_paid:
            continue
        site_lines = sum(site_line_total(r["check_id"], r["invoice_id"]) for r in paid[number])
        check(db[number] == site_lines,
              f"{label}: invoice {number} lines db {db[number]:,} = site lines {site_lines:,}")
        partial.append((number, db[number], site_paid))
    total_db = sum(db.values())
    total_paid = sum(int(r["invoice_amount"]) for r in site.values())
    print(f"     lines {total_db:,} kr, paid per site {total_paid:,} kr; "
          f"{len(partial)} invoice(s) where lines != payment: "
          + ", ".join(f"{n} ({a:,} vs {p:,})" for n, a, p in partial))


def main() -> None:
    con = sqlite3.connect(DB)
    q = lambda sql, *a: con.execute(sql, a).fetchall()

    print("-- row counts per month vs website")
    for source_file, rows in q("SELECT source_file, rows FROM load_log ORDER BY source_file"):
        fra, til = month_range(source_file[:7])
        expected = get_json("/rest/csvCount", {"vendor_id": "", "type_id": "", "org_id": "",
                                               "timabil_fra": fra, "timabil_til": til})["count"]
        check(rows == expected, f"{source_file}: {rows:,} lines, site says {expected:,}")
    total = q("SELECT COUNT(*) FROM invoice_line")[0][0]
    logged = q("SELECT SUM(rows) FROM load_log")[0][0]
    check(total == logged, f"invoice_line has {total:,} rows = sum of files {logged:,}")

    print("-- integrity")
    check(q("PRAGMA foreign_key_check") == [], "no orphan ids")
    check(q("SELECT COUNT(*) FROM invoice_line l LEFT JOIN invoice i ON i.id = l.invoice_id "
            "WHERE i.id IS NULL")[0][0] == 0, "every line belongs to an invoice")
    check(q("SELECT COUNT(*) FROM invoice WHERE invoice_number LIKE '%.0'")[0][0] == 0,
          "invoice numbers stored as text (no '.0' from float conversion)")
    broken = [n for t in ("buyer", "vendor", "cost_type")
              for (n,) in q(f"SELECT name FROM {t}") if "�" in n]
    check(broken == [], f"no broken characters in names {broken}")
    first, last = q("SELECT MIN(payment_date), MAX(payment_date) FROM invoice")[0]
    check(first >= "2025-01-01" and last <= "2025-12-31", f"dates inside 2025: {first} .. {last}")

    print("-- spot checks vs website search")
    pairs = [("Veðurstofa Íslands", "Byko ehf.", "2025-01")]
    # plus the largest and a mid-sized buyer/vendor pair of one month, chosen from the data
    ranked = q("""
        SELECT b.name, v.name, SUM(l.amount) AS s
        FROM invoice_line l JOIN invoice i ON i.id = l.invoice_id
        JOIN buyer b ON b.id = i.buyer_id JOIN vendor v ON v.id = i.vendor_id
        WHERE i.payment_date BETWEEN '2025-06-01' AND '2025-06-30'
        GROUP BY b.id, v.id ORDER BY s DESC""")
    pairs += [(ranked[0][0], ranked[0][1], "2025-06"),
              (ranked[len(ranked) // 2][0], ranked[len(ranked) // 2][1], "2025-06")]
    for buyer, vendor, ym in pairs:
        try:
            spot_check(con, buyer, vendor, ym)
        except LookupError as e:
            check(False, f"{ym} {buyer} / {vendor}: {e}")

    print(f"\n{len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
