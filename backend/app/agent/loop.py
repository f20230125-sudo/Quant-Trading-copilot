"""The copilot's tool-use loop.

A manual loop rather than the SDK tool runner, because the UI needs a
per-token text stream plus a structured event for every tool call and result
(which carries chart data the model never sees).

Yields plain dict events:
  {"type": "text", "delta": str}
  {"type": "tool_start", "id", "name"}
  {"type": "tool_result", "id", "name", "input", "ok", "error", "ui"}
  {"type": "error", "message": str}
  {"type": "done", "usage": {...}}
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from ..config import Settings
from ..market import SyntheticMarket
from .prompts import SYSTEM_PROMPT
from .tools import execute_tool, tool_definitions

log = logging.getLogger(__name__)

TOOL_DEFS = tool_definitions()
# Models that accept server-side refusal fallbacks with automatic routing.
FALLBACK_MODELS = {"claude-opus-5", "claude-fable-5", "claude-fable-5-1"}
MAX_JSON_RETRIES = 2


def request_params(settings: Settings) -> dict[str, Any]:
    params: dict[str, Any] = {
        "model": settings.claude_model,
        "max_tokens": 64_000,
        "system": SYSTEM_PROMPT,
        "tools": TOOL_DEFS,
        # System prompt + tools are identical on every request, so they cache well.
        "cache_control": {"type": "ephemeral"},
    }
    if not settings.claude_model.startswith("claude-haiku"):
        params["output_config"] = {"effort": settings.claude_effort}
    if settings.claude_model in FALLBACK_MODELS:
        params["betas"] = ["server-side-fallback-2026-07-01"]
        params["fallbacks"] = "default"
    return params


def _describe_api_error(exc: anthropic.APIError) -> str:
    if isinstance(exc, anthropic.AuthenticationError):
        return "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in backend/.env."
    if isinstance(exc, anthropic.RateLimitError):
        return "Anthropic API rate limit reached. Wait a moment and try again."
    if isinstance(exc, anthropic.APIStatusError):
        return f"Anthropic API error ({exc.status_code}): {exc.message}"
    if isinstance(exc, anthropic.APIConnectionError):
        return "Could not reach the Anthropic API. Check your network connection."
    return f"Anthropic API error: {exc}"


async def run_agent(
    client: anthropic.AsyncAnthropic,
    settings: Settings,
    market: SyntheticMarket,
    history: list[dict[str, Any]],
) -> AsyncIterator[dict[str, Any]]:
    params = request_params(settings)
    messages = list(history)
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "requests": 0}
    json_retries = 0

    for _ in range(settings.max_agent_iterations):
        try:
            async with client.beta.messages.stream(messages=messages, **params) as stream:
                async for event in stream:
                    if event.type == "text":
                        yield {"type": "text", "delta": event.text}
                    elif event.type == "content_block_start" and event.content_block.type == "tool_use":
                        yield {"type": "tool_start", "id": event.content_block.id, "name": event.content_block.name}
                response = await stream.get_final_message()
            json_retries = 0
        except ValueError:
            # Tool-input JSON the SDK couldn't parse at all (eager input streaming leaves
            # validation to the client). No tool_use id to answer, so re-issue the turn.
            json_retries += 1
            if json_retries > MAX_JSON_RETRIES:
                yield {"type": "error", "message": "The model produced malformed tool input repeatedly."}
                break
            continue
        except anthropic.APIError as exc:
            log.warning("Anthropic API error: %r", exc)
            yield {"type": "error", "message": _describe_api_error(exc)}
            break

        usage["requests"] += 1
        usage["input_tokens"] += response.usage.input_tokens
        usage["output_tokens"] += response.usage.output_tokens
        usage["cache_read_input_tokens"] += response.usage.cache_read_input_tokens or 0

        if response.stop_reason == "refusal":
            yield {"type": "text", "delta": "\n\n_The model declined to continue with this request._"}
            break

        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason == "pause_turn":
            continue
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            break
        if response.stop_reason == "max_tokens":
            # A truncated tool input can parse as a valid partial object; never run it.
            yield {"type": "error", "message": "The response hit the output limit before the tool call finished."}
            break

        results = await asyncio.gather(*(execute_tool(market, b.name, b.input) for b in tool_uses))
        for block, result in zip(tool_uses, results, strict=True):
            yield {
                "type": "tool_result",
                "id": block.id,
                "name": block.name,
                "input": block.input,
                "ok": not result.is_error,
                "error": json.loads(result.content).get("error") if result.is_error else None,
                "ui": result.ui,
            }
        # All results go back in one user message so Claude keeps making parallel calls.
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result.content,
                        **({"is_error": True} if result.is_error else {}),
                    }
                    for block, result in zip(tool_uses, results, strict=True)
                ],
            }
        )
    else:
        yield {
            "type": "text",
            "delta": f"\n\n_Stopped after {settings.max_agent_iterations} rounds of tool calls._",
        }

    yield {"type": "done", "usage": usage, "engine": "claude"}
