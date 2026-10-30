"""The MCP server, tested the way a client uses it: started as a subprocess, spoken to over stdio.

One server process for the whole file (starting it and loading the search model is slow);
every call is made up front and the tests check the replies. Runs against the real data,
no network. The first run downloads nothing: the search model is already in data/hf.
"""

import asyncio
import json
import sys

import pytest
from mcp import Client, StdioServerParameters

from opnir_agent import db
from opnir_agent.config import DB_PATH, ROOT
from test_db_guard import WRITES

COUNT_BUYERS = {"query": "SELECT COUNT(*) FROM buyer"}
CALLS = {
    "count": ("run_sql", COUNT_BUYERS),
    "find": ("find_names", {"table": "buyer", "text": "veðurstof"}),
    "find_bad_table": ("find_names", {"table": "sqlite_master", "text": "x"}),
    "person_lookup": ("run_sql", {"query": "SELECT COUNT(*) FROM vendor "
                                           "WHERE name = 'Jón Jónsson'"}),
    "person_raw": ("run_sql", {"query": "SELECT name FROM main.vendor"}),
    "search": ("search_documents",
               {"query": "Eru greiðslur til einstaklinga birtar á opnirreikningar.is?"}),
    **{f"write{i}": ("run_sql", {"query": sql}) for i, sql in enumerate(WRITES)},
    "count_after": ("run_sql", COUNT_BUYERS),
}


async def _session():
    params = StdioServerParameters(command=sys.executable, args=["-m", "opnir_agent.mcp_server"],
                                   cwd=str(ROOT))
    async with Client(params) as client:
        tools = await client.list_tools()
        replies = {key: await client.call_tool(name, args) for key, (name, args) in CALLS.items()}
    return tools.tools, replies


@pytest.fixture(scope="module")
def server():
    before = DB_PATH.stat()
    tools, replies = asyncio.run(_session())
    after = DB_PATH.stat()
    return tools, replies, (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)


def _json(reply):
    assert not reply.is_error, reply.content[0].text
    return json.loads(reply.content[0].text)


def test_three_read_only_tools(server):
    tools, _, _ = server
    assert sorted(t.name for t in tools) == ["find_names", "run_sql", "search_documents"]
    assert all(t.annotations.read_only_hint for t in tools)


def test_sql_matches_direct_query(server):
    _, replies, _ = server
    direct = db.run_query(db.connect(), COUNT_BUYERS["query"])
    assert _json(replies["count"]) == direct


def test_find_names(server):
    _, replies, _ = server
    assert replies["find"].structured_content == {"result": ["Veðurstofa Íslands"]}
    assert replies["find_bad_table"].is_error


def test_people_hidden_through_mcp(server):
    _, replies, _ = server
    assert _json(replies["person_lookup"])["rows"] == [[0]]
    assert replies["person_raw"].is_error and "hidden" in replies["person_raw"].content[0].text


@pytest.mark.parametrize("i", range(len(WRITES)))
def test_writes_refused_through_mcp(server, i):
    _, replies, _ = server
    reply = replies[f"write{i}"]
    assert reply.is_error, f"not refused: {WRITES[i]}"
    # the model must see why, not only "Error executing tool"
    assert "allowed" in reply.content[0].text or "statement" in reply.content[0].text


def test_database_unchanged(server):
    _, replies, unchanged = server
    assert unchanged, "data/opnir.db changed during the session"
    assert _json(replies["count_after"]) == _json(replies["count"])


def test_search_returns_cited_passages(server):
    _, replies, _ = server
    passages = replies["search"].structured_content["result"]
    assert len(passages) == 5
    assert all(set(p) == {"title", "url", "text"} for p in passages)
    assert passages[0]["url"] == "https://opnirreikningar.is/info"
