"""Settings read from .env: the Azure OpenAI endpoint, key and deployment."""

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "opnir.db"


def client_from_env() -> tuple[OpenAI, str]:
    """An OpenAI client pointed at the Azure v1 endpoint, and the deployment name."""
    load_dotenv(ROOT / ".env")
    missing = [k for k in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY",
                           "AZURE_OPENAI_DEPLOYMENT") if not os.getenv(k)]
    if missing:
        raise SystemExit(f"missing in .env: {', '.join(missing)} (see .env.example)")
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    if not endpoint.endswith("/openai/v1"):
        endpoint += "/openai/v1"
    return OpenAI(api_key=os.environ["AZURE_OPENAI_API_KEY"], base_url=endpoint + "/"), \
        os.environ["AZURE_OPENAI_DEPLOYMENT"]
