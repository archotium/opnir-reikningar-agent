"""Ask the agent one question from the command line.

Usage: python -m opnir_agent "Hvað greiddi Veðurstofa Íslands mikið til Byko árið 2025?"
"""

import sys

from .agent import Agent


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    answer = Agent().ask(" ".join(sys.argv[1:]))
    for i, step in enumerate(answer.steps, 1):
        if step.tool == "run_sql":
            print(f"--- SQL {i} ---\n{step.arguments['query']}\n")
        else:
            print(f"--- {step.tool} {i}: {step.arguments} -> {step.result}\n")
    print(answer.text)
    print(f"\n[{len(answer.steps)} tool calls, tokens in/out "
          f"{answer.input_tokens:,}/{answer.output_tokens:,}]")


if __name__ == "__main__":
    main()
