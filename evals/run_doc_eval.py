"""Score document search (RAG) on questions whose right source is known.

Two levels, so a failure can be traced to the part that caused it:

  retrieval   is a passage from the right document, containing the expected
              fact, among the top 5 the search returns? (no language model)
  answer      does the agent's final text contain the expected fact AND cite
              the right document's URL?  (--agent; calls Azure OpenAI)

An answer that states the fact without citing the right source fails: an
uncited answer can't be checked by the reader, which is the point of RAG.

Usage: python evals/run_doc_eval.py [--agent]
"""

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from opnir_agent import docs  # noqa: E402

HERE = Path(__file__).resolve().parent
QUESTIONS = HERE / "doc_questions.jsonl"
RESULTS = HERE / "results"


def main(with_agent: bool) -> None:
    questions = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines()]
    urls = {s["id"]: s["url"] for s in docs.load_sources()}
    index = docs.DocumentIndex()
    agent = None
    if with_agent:
        from opnir_agent.agent import Agent
        agent = Agent(index=index)

    results, hits1, hits5, passed = [], 0, 0, 0
    for q in questions:
        found = index.search(q["question"])
        # a hit is a passage from the right document that contains the expected fact:
        # the right document alone isn't enough if the answer is in a passage not returned
        ranks = [i for i, p in enumerate(found, 1) if p["doc"] in q["docs"]
                 and re.search(q["expect"], p["text"], re.IGNORECASE)]
        rank = ranks[0] if ranks else None
        hits1 += rank == 1
        hits5 += rank is not None
        row = {**q, "rank": rank, "top": [(p["doc"], p["score"]) for p in found]}
        if agent:
            start = time.monotonic()
            answer = agent.ask(q["question"])
            has_fact = re.search(q["expect"], answer.text, re.IGNORECASE) is not None
            cites = any(urls[d] in answer.text for d in q["docs"])
            row.update(answer=answer.text, has_fact=has_fact, cites_source=cites,
                       passed=has_fact and cites, tools=[s.tool for s in answer.steps],
                       seconds=round(time.monotonic() - start, 1),
                       input_tokens=answer.input_tokens, output_tokens=answer.output_tokens)
            passed += row["passed"]
        results.append(row)
        mark = "" if not agent else (" PASS" if row["passed"] else
                                     f" FAIL (fact {row['has_fact']}, cites {row['cites_source']})")
        print(f"{q['id']}  rank {rank}{mark}  {q['question']}")

    n = len(questions)
    summary = {"questions": n, "retrieval_hit_at_1": hits1, "retrieval_hit_at_5": hits5}
    if agent:
        summary.update(answers_passed=passed,
                       input_tokens=sum(r["input_tokens"] for r in results),
                       output_tokens=sum(r["output_tokens"] for r in results))
    print(summary)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"doc_questions_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False,
                              indent=2), encoding="utf-8")


if __name__ == "__main__":
    main("--agent" in sys.argv)
