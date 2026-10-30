"""The agent's three tools as an MCP server, so any MCP client can use them.

    MCP client (an editor, an AI assistant) ─► this server ─► db.py / docs.py
           ▲  the client's own model decides            │
           └──────────── which tool to call ◄── result ─┘

MCP (Model Context Protocol) is a standard way for an AI application to find and
call tools it didn't ship with. Here the client brings the language model; this
server brings only the tools, so it needs no Azure key and makes no model calls.

The tools are the same functions agent.py uses, so the read-only guard in db.py
applies whichever client calls them: nothing in this file can loosen it.

Transport is stdio: the client starts this file as a subprocess and they talk
JSON over its stdin/stdout. Anything else printed to stdout would corrupt that
channel, so nothing here prints; logs go to stderr.

Run: python -m opnir_agent.mcp_server   (normally the client starts it; see .mcp.json)
"""

import threading
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from . import db, docs
from .agent import INSTRUCTIONS

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)

_con = db.connect()
_index: docs.DocumentIndex | None = None  # the embedding model is slow to load: on first search
# The SDK runs each call on a worker thread. One connection and one timeout per call can't be
# shared by two calls at once, so calls take turns.
_lock = threading.Lock()

server = MCPServer(
    name="opnir-reikningar",
    instructions=INSTRUCTIONS.format(schema=db.schema_text(_con)),
)


@server.tool(annotations=READ_ONLY)
def run_sql(query: str) -> dict:
    """Run one read-only SQLite SELECT query on the 2025 invoice database
    (opnirreikningar.is). Returns columns, rows (max 200) and whether rows were cut off."""
    with _lock:
        try:
            return db.run_query(_con, query)
        except db.QueryError as e:
            raise ToolError(str(e)) from None  # shown to the model so it can fix its query


@server.tool(annotations=READ_ONLY)
def find_names(table: Literal["buyer", "vendor", "cost_type"], text: str) -> list[str]:
    """Find the exact names of agencies (table 'buyer'), suppliers ('vendor') or cost types
    ('cost_type') matching a partial or misspelt name, e.g. 'veðurstof'."""
    with _lock:
        try:
            return db.find_names(_con, table, text)
        except db.QueryError as e:
            raise ToolError(str(e)) from None


@server.tool(annotations=READ_ONLY)
def search_documents(query: str) -> list[dict]:
    """Search Fjársýslan's web pages and the opnirreikningar.is description by meaning
    (query in Icelandic). Returns the 5 closest passages with title, URL and text; cite
    the URL of each passage you use. The first search takes 10-20 s while the model loads."""
    global _index
    with _lock:
        _index = _index or docs.DocumentIndex()
        return [{k: p[k] for k in ("title", "url", "text")} for p in _index.search(query)]


if __name__ == "__main__":
    server.run("stdio")
