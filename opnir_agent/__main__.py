"""Ask the agent one question from the command line.

Usage: python -m opnir_agent "Hvað greiddi Veðurstofa Íslands mikið til Byko árið 2025?"
"""

import os
import sys

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")  # no model-loading bars in the answer

from .agent import Agent


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    answer = Agent().ask(" ".join(sys.argv[1:]))
    for i, step in enumerate(answer.steps, 1):
        if step.tool == "run_sql":
            print(f"--- SQL {i} ---\n{step.arguments['query']}\n")
        elif step.tool == "search_documents" and isinstance(step.result, list):
            # the passages themselves are long; their sources are what a reader checks
            pages = dict.fromkeys(f"  {p['title']}  {p['url']}" for p in step.result)
            print(f"--- search_documents {i}: {step.arguments['query']}\n"
                  f"{len(step.result)} passages from:\n" + "\n".join(pages) + "\n")
        else:
            print(f"--- {step.tool} {i}: {step.arguments} -> {step.result}\n")
    print(answer.text.replace("**", ""))  # markdown bold doesn't render in a terminal
    print(f"\n[{len(answer.steps)} tool calls, tokens in/out "
          f"{answer.input_tokens:,}/{answer.output_tokens:,}]")


if __name__ == "__main__":
    main()
