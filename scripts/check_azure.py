"""Check that the Azure OpenAI deployment in .env works, including tool calling.

1. Sends one Icelandic question and prints the answer.
2. Offers the model a tool and checks it asks to call it, which is what the
   agent depends on.

Never prints the API key. Usage: python scripts/check_azure.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from opnir_agent.config import client_from_env  # noqa: E402


def main() -> None:
    client, deployment = client_from_env()
    print(f"endpoint:   {client.base_url}")
    print(f"deployment: {deployment}\n")

    reply = client.responses.create(
        model=deployment,
        input="Svaraðu í einni setningu á íslensku: hvað gerir Fjársýsla ríkisins?",
    )
    print("1. plain answer:")
    print("  ", reply.output_text)
    print(f"   tokens in/out: {reply.usage.input_tokens}/{reply.usage.output_tokens}\n")

    tools = [{
        "type": "function",
        "name": "count_invoices",
        "description": "Count paid state invoices for an agency in a given month.",
        "parameters": {
            "type": "object",
            "properties": {
                "agency": {"type": "string", "description": "Agency name in Icelandic"},
                "month": {"type": "string", "description": "Month as YYYY-MM"},
            },
            "required": ["agency", "month"],
            "additionalProperties": False,
        },
    }]
    reply = client.responses.create(
        model=deployment,
        input="Hversu marga reikninga greiddi Veðurstofa Íslands í júní 2025?",
        tools=tools,
    )
    calls = [item for item in reply.output if item.type == "function_call"]
    print("2. tool calling:")
    if not calls:
        print("   FAIL: the model answered without calling the tool:", reply.output_text)
        sys.exit(1)
    for call in calls:
        print(f"   PASS: model asked for {call.name}({json.dumps(json.loads(call.arguments), ensure_ascii=False)})")


if __name__ == "__main__":
    main()
