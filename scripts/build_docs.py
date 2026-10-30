"""Download the documents in docs_sources.json and build the search index.

Files land in data/docs/ (existing files are skipped); the index goes to
data/docs_index/. The first run also downloads the embedding model (~1.1 GB)
to data/hf/.

Usage: python scripts/build_docs.py
"""

import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from opnir_agent import docs  # noqa: E402


def main() -> None:
    docs.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    for source in docs.load_sources():
        out = docs.DOCS_DIR / source["file"]
        if out.exists():
            print(f"skip {out.name} (exists)")
            continue
        with urllib.request.urlopen(source.get("download_url", source["url"]), timeout=120) as resp:
            out.write_bytes(resp.read())
        print(f"saved {out.name} ({out.stat().st_size / 1e3:.0f} kB)")
        time.sleep(1)  # one request a second: these are a public agency's servers
    print(docs.build_index())


if __name__ == "__main__":
    main()
