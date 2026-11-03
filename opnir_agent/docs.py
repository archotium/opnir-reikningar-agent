"""Search over documents (RAG): find the passages that answer a question, with their source.

    build (once):   document ─► pages ─► passages ─► embedding model ─► vectors on disk
    search (each question):  question ─► embedding model ─► closest passages ─► model

An embedding model turns a text into a list of numbers (a vector) so that texts
with similar meaning get similar vectors, even when they share no words. That
matters in Icelandic, where "ríkisreikningurinn" and "ríkisreiknings" are the
same word to a reader but different strings to a keyword search.

The model runs locally (multilingual-e5-base, ~1.1 GB, cached under data/hf),
so documents never leave the machine. With a few thousand passages, comparing
the question against every vector with numpy takes milliseconds; a vector
database would add a dependency without making anything faster.

Each passage keeps its document, page and URL, so the agent can cite where an
answer came from and a reader can check it.
"""

import html
import json
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .config import ROOT

DOCS_DIR = ROOT / "data" / "docs"
INDEX_DIR = ROOT / "data" / "docs_index"
SOURCES = ROOT / "docs_sources.json"
MODEL_NAME = "intfloat/multilingual-e5-base"
os.environ.setdefault("HF_HOME", str(ROOT / "data" / "hf"))  # keep the model on this drive

PASSAGE_CHARS = 1000  # target passage length; about 250 tokens
OVERLAP_CHARS = 300   # text repeated from the end of one passage at the start of the next
TOP_K = 5
MAX_NUMBER_SHARE = 0.35  # passages that are mostly digits are table rows: skipped (see DATA_NOTES)
BOILERPLATE_SHARE = 0.3  # a line on more than this share of pages is site navigation


@dataclass
class Passage:
    doc: str      # document id from docs_sources.json
    title: str
    url: str
    page: int | None  # PDF page number (1-based); None for web pages
    text: str


def load_sources() -> list[dict]:
    return json.loads(SOURCES.read_text(encoding="utf-8"))


def _html_text(raw: str) -> str:
    """Visible text of a web page, one line per block. Only <main> when the page has one,
    so menus repeated on every page don't end up in every passage."""
    main = re.search(r"(?is)<main\b.*?</main>", raw)
    raw = main.group(0) if main else raw
    raw = re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|tr)>", "\n", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    lines = (re.sub(r"\s+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def _pages(source: dict) -> list[tuple[int | None, str]]:
    """The text of a downloaded source, page by page."""
    path = DOCS_DIR / source["file"]
    if source["kind"] == "pdf":
        from pypdf import PdfReader
        return [(i, page.extract_text() or "") for i, page in enumerate(PdfReader(path).pages, 1)]
    return [(None, _html_text(path.read_text(encoding="utf-8")))]


def _split(text: str) -> list[str]:
    """Split a page into passages of about PASSAGE_CHARS, breaking between paragraphs."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n(?=[A-ZÁÐÉÍÓÚÝÞÆÖ•])", text) if p.strip()]
    passages, current, tail = [], "", []
    for p in paragraphs:
        if current and len(current) + len(p) > PASSAGE_CHARS:
            passages.append(current)
            # Start the next passage with the last short paragraphs of this one, so a heading
            # and the sentence that answers it can't end up in different passages.
            current = "\n".join(tail)
        current = f"{current}\n{p}".strip()
        tail = [q for q in tail + [p] if len(q) <= OVERLAP_CHARS]
        while sum(map(len, tail)) > OVERLAP_CHARS:
            tail.pop(0)
        while len(current) > 2 * PASSAGE_CHARS:  # one huge paragraph: cut at a sentence end
            cut = current.rfind(". ", 0, PASSAGE_CHARS) + 1 or PASSAGE_CHARS
            passages.append(current[:cut].strip())
            current = current[cut:].strip()
    if current:
        passages.append(current)
    return passages


def _is_table(text: str) -> bool:
    chars = [c for c in text if not c.isspace()]
    return not chars or sum(c.isdigit() or c in ".,-" for c in chars) / len(chars) > MAX_NUMBER_SHARE


def _model():
    from sentence_transformers import SentenceTransformer  # slow import: only when needed
    try:  # cached under data/hf after the first build: load it without asking the Hub
        return SentenceTransformer(MODEL_NAME, local_files_only=True)
    except OSError:  # not downloaded yet
        return SentenceTransformer(MODEL_NAME)


def _drop_boilerplate(pages: list[tuple[dict, int | None, str]]) -> list[tuple[dict, int | None, str]]:
    """Remove lines that repeat on many pages (site menus, footers): they say nothing about
    any one page, and left in they make every passage look alike to the search."""
    line_pages = Counter(line for _, _, text in pages for line in set(text.splitlines()))
    limit = max(3, BOILERPLATE_SHARE * len(pages))
    return [(source, page, "\n".join(l for l in text.splitlines() if line_pages[l] < limit))
            for source, page, text in pages]


def build_index() -> dict:
    """Split every downloaded source into passages, embed them, and save the index."""
    pages = [(source, page, text) for source in load_sources() for page, text in _pages(source)]
    passages, skipped = [], 0
    for source, page, text in _drop_boilerplate(pages):
        for chunk in _split(text):
            if _is_table(chunk):
                skipped += 1
                continue
            passages.append(Passage(source["id"], source["title"], source["url"], page, chunk))
    # e5 models are trained with these prefixes; leaving them out costs accuracy
    vectors = _model().encode([f"passage: {p.text}" for p in passages], batch_size=32,
                              normalize_embeddings=True, show_progress_bar=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    np.save(INDEX_DIR / "vectors.npy", vectors.astype(np.float32))
    (INDEX_DIR / "passages.json").write_text(
        json.dumps([asdict(p) for p in passages], ensure_ascii=False), encoding="utf-8")
    return {"passages": len(passages), "table_passages_skipped": skipped}


class DocumentIndex:
    def __init__(self):
        if not (INDEX_DIR / "vectors.npy").exists():
            raise SystemExit(f"{INDEX_DIR} not found; run scripts/build_docs.py")
        self.vectors = np.load(INDEX_DIR / "vectors.npy")
        self.passages = [Passage(**p) for p in
                         json.loads((INDEX_DIR / "passages.json").read_text(encoding="utf-8"))]
        self.model = _model()

    def search(self, query: str, k: int = TOP_K) -> list[dict]:
        """The k passages closest in meaning to the query, best first, with a similarity score."""
        q = self.model.encode([f"query: {query}"], normalize_embeddings=True)[0]
        scores = self.vectors @ q  # vectors are normalised, so this is cosine similarity
        best = np.argsort(-scores)[:k]
        return [{**asdict(self.passages[i]), "score": round(float(scores[i]), 3)} for i in best]
