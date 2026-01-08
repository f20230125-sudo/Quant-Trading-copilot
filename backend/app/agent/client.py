import logging
import re
from pathlib import Path

import anthropic

from ..config import Settings

log = logging.getLogger(__name__)

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def build_client(settings: Settings) -> anthropic.AsyncAnthropic | None:
    """Anthropic client from the configured key, else the environment or an `ant auth login` profile.

    Returns None when no credentials exist: the SDK constructs a client without any
    and only fails at request time, so check up front.
    """
    if settings.anthropic_api_key:
        return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    client = anthropic.AsyncAnthropic()
    if client.api_key or client.auth_token or client.credentials:
        return client
    log.info("No Anthropic credentials: the copilot will use the local analyst engine.")
    return None


async def verify_key(api_key: str) -> anthropic.AsyncAnthropic:
    """Return a client for ``api_key`` after confirming the key works (a free models-list call).

    Raises the SDK's typed errors (AuthenticationError, APIConnectionError, ...).
    """
    client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=1, timeout=15)
    await client.models.list(limit=1)
    return client


def save_key(api_key: str, path: Path = ENV_PATH) -> None:
    """Write ANTHROPIC_API_KEY into the backend .env, replacing any existing value."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    entry = f"ANTHROPIC_API_KEY={api_key}"
    replaced = False
    for i, line in enumerate(lines):
        if re.match(r"\s*ANTHROPIC_API_KEY\s*=", line):
            lines[i] = entry
            replaced = True
    if not replaced:
        lines.append(entry)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
