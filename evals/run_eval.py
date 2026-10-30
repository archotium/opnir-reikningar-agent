"""Score the agent on questions whose right answer is computed by a reference query.

Each question in a .jsonl file has a reference_sql; the expected answer is
whatever that query returns now, so the eval follows the data if it is
rebuilt. The agent's *final text* is checked, i.e. what a user would read:

  number       some number in the answer is within `tolerance` (relative) of
               the expected value; tolerance 0 means exact
  names        every expected name appears in the answer
  name_number  the expected name and number both appear

An answer also fails if the agent ran no SQL: a right number it didn't
compute (e.g. one quoted from its instructions) is luck, not an answer.

Results (answer, SQL used, tokens, pass/fail) are written to evals/results/.

Usage: python evals/run_eval.py [evals/sql_questions.jsonl]
"""

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from opnir_agent import db  # noqa: E402
from opnir_agent.agent import Agent  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"

MULTIPLIERS = [
    (r"milljarð\w*|ma\.?\s?kr", 1e9),
    (r"milljón\w*|millj\.|m\.?\s?kr", 1e6),
    (r"þúsund\w*|þús\.", 1e3),
]

# 13.213.513.954 | 13 213 513 954 | 13,213,513,954 | 242,1 | 157
NUMBER = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d{1,3}(?:[   ]\d{3})+(?:,\d+)?"
    r"|\d{1,3}(?:,\d{3}){2,}|\d+(?:,\d+)?)(?![\d])"
    r"(\s*(?:" + "|".join(p for p, _ in MULTIPLIERS) + r"))?",
    re.IGNORECASE)


def numbers_in(text: str) -> list[float]:
    """Every number in an Icelandic (or English-formatted) answer, with milljarðar etc. applied."""
    found = []
    for digits, unit in NUMBER.findall(text):
        if re.fullmatch(r"\d{1,3}(?:,\d{3}){2,}", digits):  # English thousands commas
            value = float(digits.replace(",", ""))
        else:
            value = float(re.sub(r"[.\s  ]", "", digits).replace(",", "."))
        for pattern, factor in MULTIPLIERS:
            if unit and re.search(pattern, unit, re.IGNORECASE):
                value *= factor
        found.append(value)
    return found


def number_ok(text: str, expected: float, tolerance: float) -> bool:
    return any(abs(n - expected) <= tolerance * abs(expected) for n in numbers_in(text))


def name_ok(text: str, name: str) -> bool:
    return name.casefold() in text.casefold()


def grade(case: dict, rows: list, text: str) -> tuple[bool, str]:
    if case["check"] == "number":
        expected = rows[0][0]
        return number_ok(text, expected, case["tolerance"]), f"{expected:,}"
    if case["check"] == "name_number":
        name, expected = rows[0]
        ok = name_ok(text, name) and number_ok(text, expected, case["tolerance"])
        return ok, f"{name} / {expected:,}"
    if case["check"] == "names":
        names = [r[0] for r in rows]
        missing = [n for n in names if not name_ok(text, n)]
        return not missing, f"{len(names)} names" + (f", missing {missing}" if missing else "")
    raise ValueError(case["check"])


def main(path: Path) -> None:
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    agent = Agent()
    results, passed, tokens_in, tokens_out = [], 0, 0, 0
    for case in cases:
        rows = db.run_query(agent.con, case["reference_sql"])["rows"]
        start = time.perf_counter()
        answer = agent.ask(case["question"])
        seconds = time.perf_counter() - start
        ok, expected = grade(case, rows, answer.text)
        if not answer.queries:
            ok, expected = False, f"{expected} (no SQL run)"
        passed += ok
        tokens_in += answer.input_tokens
        tokens_out += answer.output_tokens
        print(f"{'PASS' if ok else 'FAIL'} {case['id']} ({seconds:.1f} s, {len(answer.steps)} tools) "
              f"expected {expected}\n     {case['question']}\n     -> {answer.text[:300]!r}\n")
        results.append({**case, "expected": expected, "passed": ok, "answer": answer.text,
                        "queries": answer.queries, "tool_calls": len(answer.steps),
                        "seconds": round(seconds, 1), "input_tokens": answer.input_tokens,
                        "output_tokens": answer.output_tokens,
                        "stopped_early": answer.stopped_early})
    summary = {"file": path.name, "deployment": agent.deployment, "passed": passed,
               "total": len(cases), "input_tokens": tokens_in, "output_tokens": tokens_out,
               "run_at": datetime.now().isoformat(timespec="seconds")}
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{path.stem}_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False,
                              indent=2), encoding="utf-8")
    print(f"{passed}/{len(cases)} passed; tokens in/out {tokens_in:,}/{tokens_out:,}; saved {out.name}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1
         else Path(__file__).resolve().parent / "sql_questions.jsonl")
