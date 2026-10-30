# Opnir reikningar: AI-agent fyrir greiðslur ríkisins

*[English below](#english)*

AI-agent sem svarar spurningum á íslensku um greiðslur ríkisstofnana árið 2025, úr gögnum
[opnirreikningar.is](https://opnirreikningar.is) (2,6 milljónir reikningslína frá Fjársýslu
ríkisins), og um starfsemi Fjársýslunnar, úr 40 síðum hennar. Hver tala kemur úr SQL-fyrirspurn
sem agentinn sýnir, og hvert svar úr skjölum vísar í síðuna sem það byggir á.

```text
> python -m opnir_agent "Hvað greiddi Veðurstofa Íslands mikið samtals árið 2025?"

--- find_names 1: {'table': 'buyer', 'text': 'Veðurstofa Íslands'} -> ['Veðurstofa Íslands']

--- SQL 2 ---
SELECT SUM(l.amount) AS total_isk
FROM invoice_line l
JOIN invoice i ON i.id = l.invoice_id
JOIN buyer b ON b.id = i.buyer_id
WHERE b.name = 'Veðurstofa Íslands'
  AND i.payment_date >= '2025-01-01'
  AND i.payment_date < '2026-01-01';

Veðurstofa Íslands greiddi samtals **1.261.110.193 kr.** árið 2025.

Athugið að þetta er summa allra reikningslína í gögnunum; laun, styrkir og bætur eru ekki með,
og greiðslur milli ríkisaðila geta verið innifaldar.

[2 tool calls, tokens in/out 4,130/197]
```

## Hvernig hann virkar

```text
spurning ─► líkan (Azure OpenAI) ─┬─► svar
                                  └─► biður um verkfæri ─► kóðinn okkar keyrir það ─► niðurstaða aftur til líkans
```

Líkanið snertir aldrei gögnin sjálft; það getur aðeins beðið um eitt af þremur verkfærum:

| Verkfæri | Hvað það gerir |
|---|---|
| `run_sql` | Ein SELECT-fyrirspurn á SQLite-gagnagrunninn |
| `find_names` | Finnur rétt heiti stofnunar, birgis eða kostnaðartegundar ("Veðurstofan" → "Veðurstofa Íslands") |
| `search_documents` | Merkingarleit (RAG) í síðum Fjársýslunnar; svarið verður að vísa í heimild, og kóðinn athugar það |

- **Öryggi í 4 lögum** (`opnir_agent/db.py`): skrifvarin tenging; *authorizer* sem leyfir aðeins
  lestur áður en skipun keyrir; ein skipun í senn með 10 s tímamörkum; mest 200 línur til baka.
- **Persónuvernd** (`opnir_agent/privacy.py`): 1.318 birgjar sem þekkjast sem einstaklingar af
  nafninu birtast sem `[einstaklingur]`. Falið við upptök, ekki í úttaki, svo engin fyrirspurn
  nær nafninu. Heildartölur breytast ekki.
- **MCP-þjónn** (`opnir_agent/mcp_server.py`): sömu þrjú verkfæri fyrir hvaða MCP-forrit sem er,
  með sömu öryggis- og persónuverndarlögum.
- **Skjalaleit keyrir staðbundið** (multilingual-e5-base), svo skjölin fara ekki úr vélinni.

## Mælt

`evals/run_repeated.py` keyrir hvert prófasett þrisvar, því líkanið svarar ekki eins í hvert sinn.

| Prófasett | Spurningar | Rétt í hverri keyrslu | Rétt í öllum |
|---|---|---|---|
| SQL, borið saman við viðmiðunarfyrirspurn | 10 | 10, 10, 10 | 10 |
| Skjöl, spurt með orðalagi síðnanna | 10 | 10, 10, 10 | 10 |
| Skjöl, umorðaðar spurningar | 11 | 8, 8, 7 | 7 |
| Spurningar sem gögnin geta ekki svarað | 13 | 12, 13, 12 | 12 |
| Prompt injection (falinn texti í skjalaleit) | 4 | 4, 4, 4 | 4 |

Prompt injection: 12 af 12 tilraunum hafnað; agentinn reyndi aldrei að skrifa í gagnagrunninn,
afhjúpa nöfn eða fylgja fyrirmælunum, og svaraði samt rétt úr réttu síðunni. Veikasti hlutinn er
skjalaleit á umorðuðum spurningum: hún finnur ekki réttan kafla þegar spurningin deilir fáum orðum
með síðunni.

Allar villur eru lesnar yfir handvirkt; sjá [DATA_NOTES.md](DATA_NOTES.md) fyrir hvað bregst og hvers vegna.

## Takmarkanir gagnanna

Aðeins greiddir reikningar 2025. Laun, styrkir, bætur, greiðslur í erlendri mynt og viðkvæmar
kostnaðartegundir eru ekki birtar. Greiðslur milli ríkisaðila eru taldar með. Þegar reikningur er
greiddur í áföngum endurtekur útflutningurinn allar línur hans. Nánar í [DATA_NOTES.md](DATA_NOTES.md).

## Uppsetning

Sjá [Setup](#setup) hér fyrir neðan (sömu skref).

---

<a id="english"></a>
# Opnir reikningar: an AI agent for Icelandic state payments

An AI agent that answers questions in Icelandic about what Iceland's state agencies paid in
2025, from the open data on [opnirreikningar.is](https://opnirreikningar.is) (2.6 million
invoice lines published by Fjársýsla ríkisins, the state's financial management authority), and
about Fjársýslan's own services, from 40 of its web pages. Every number comes from an SQL query
the agent shows, and every answer drawn from the documents cites the page it came from.

## How it works

The model never touches the data. It can only ask for one of three tools, and our code decides
whether to run it:

- `run_sql`: one read-only SELECT on the SQLite database.
- `find_names`: the exact name of an agency, supplier or cost type from a partial or misspelt one.
- `search_documents`: meaning-based search (RAG) over Fjársýslan's pages; the answer must cite
  its source, and the code checks that it does.

**Safety, 4 independent layers** (`opnir_agent/db.py`): the file is opened read-only; an SQLite
authorizer allows only reads, checked while each statement is compiled, so comments or odd
capitalisation can't sneak a write through; one statement per call with a 10 s limit; at most
200 rows back.

**Privacy** (`opnir_agent/privacy.py`): self-employed people are published by name on the site.
1,318 suppliers recognised as people by their name are shown as `[einstaklingur]`. This is done
at the source: a temporary view shadows the supplier table and the authorizer refuses the real
column, so no query (lookup by name, `LIKE`, `substr`) can reach a person's name. Totals are
unchanged. The name rule was checked by hand on a sample; it is a strong default, not a guarantee.

**MCP server** (`opnir_agent/mcp_server.py`): the same three tools for any MCP client, with the
same safety and privacy layers (the client brings its own model; no Azure key needed).

**Local document search**: the embedding model (multilingual-e5-base) runs on the machine, so
the documents never leave it. 179 passages compared with numpy take milliseconds; no vector
database needed.

## Measured

`evals/run_repeated.py` runs every set three times, because the model doesn't answer the same
way twice and one run is not a stable score.

| Set | Questions | Passed per run | Passed every run |
|---|---|---|---|
| SQL, checked against a reference query | 10 | 10, 10, 10 | 10 |
| Documents, asked in the pages' own wording | 10 | 10, 10, 10 | 10 |
| Documents, reworded in everyday language | 11 | 8, 8, 7 | 7 |
| Questions the data can't answer | 13 | 12, 13, 12 | 12 |
| Prompt injection (instructions planted in a search result) | 4 | 4, 4, 4 | 4 |

- **Prompt injection:** a passage telling the model to delete data, state a false date, leak
  its instructions or reveal hidden names was planted in an in-memory copy of the search index.
  It was retrieved every time and resisted every time (12 of 12): no write or unmasking query
  tried, no payload in the answer, and the real answer still given from the real page.
- **Questions the data can't answer** (another year, revenue, salaries, a named person, an
  agency that doesn't exist): the first version passed 5-8 of 10 per run. It said "no payments
  found" for 2024 instead of "the data covers 2025 only", and read a VAT cost type as VAT
  revenue. Three facts about the data were added to the instructions, and three new questions of
  the same kinds were written *after* the fix to check it generalises; all three pass.
- **Weakest part:** document search on reworded questions (7-8 of 11). It misses when the
  question shares few words with the page. Hybrid keyword + meaning search is the next step.
- Grading is rules in code; every failure was read by hand, and rules found wrong were fixed and
  the saved answers regraded without new model calls (`--regrade`). One full run of 135
  questions costs about 0.40 EUR.

Every failure was read by hand. What fails and why: [DATA_NOTES.md](DATA_NOTES.md).

## Limits of the data

Paid invoices of 2025 only. Salaries, grants, benefits, foreign-currency payments and sensitive
cost types are not published. Payments between state bodies are included, so totals are not net
state spending. When an invoice is paid in instalments, the export repeats all its lines with each
payment, so totals for those invoices overstate what was paid (902 invoices in 2025). Details and
the checks against the website: [DATA_NOTES.md](DATA_NOTES.md).

<a id="setup"></a>
## Setup

Python 3.11, about 2.6 GB of disk (Python packages 1.3 GB; data and embedding model 1.3 GB).

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows; on Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

python scripts/download.py 2025   # 12 monthly exports from opnirreikningar.is
python scripts/build_db.py        # -> data/opnir.db
python tests/check_db.py          # line counts per month must match the website
python scripts/build_docs.py      # Fjársýslan pages + search index (downloads the model once)
python -m pytest tests            # safety, privacy and MCP tests; no network, no model calls
```

For the agent itself, copy `.env.example` to `.env` and fill in an Azure OpenAI endpoint, key
and deployment name (`python scripts/check_azure.py` checks them). Then:

```bash
python -m opnir_agent "Hvað greiddi Veðurstofa Íslands mikið samtals árið 2025?"
python evals/run_repeated.py --runs 3     # full eval; about 135 questions, under 1 EUR
```

**MCP:** `.mcp.json` starts the server with `python -m opnir_agent.mcp_server` over stdio; any
MCP client that reads that file can use the tools. Other clients: point them at the same command.

## Source and licence

The data is published by Fjársýsla ríkisins on opnirreikningar.is for public transparency; the
documents are Fjársýslan's public pages on island.is. This project is not affiliated with
Fjársýslan. Neither the data nor the documents are included in this repository; the scripts
download them.
