"""Download one year of paid state invoices from opnirreikningar.is.

The site's export is capped at 500,000 rows, so the year is fetched one
month at a time (about 150-250k rows each). Files land in data/raw/ as
YYYY-MM.xlsx. Existing files are skipped.

Usage: python scripts/download.py 2025
"""

import calendar
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://opnirreikningar.is/rest"
RAW = Path(__file__).resolve().parent.parent / "data" / "raw"


def month_params(year: int, month: int) -> str:
    last = calendar.monthrange(year, month)[1]
    return urllib.parse.urlencode({
        "vendor_id": "", "type_id": "", "org_id": "",
        "timabil_fra": f"01.{month:02d}.{year}",
        "timabil_til": f"{last:02d}.{month:02d}.{year}",
    })


def main(year: int) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for month in range(1, 13):
        out = RAW / f"{year}-{month:02d}.xlsx"
        if out.exists():
            print(f"skip {out.name} (exists)")
            continue
        url = f"{BASE}/csvExport?{month_params(year, month)}"
        with urllib.request.urlopen(url, timeout=300) as resp:
            out.write_bytes(resp.read())
        print(f"saved {out.name} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2025)
