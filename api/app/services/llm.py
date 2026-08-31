"""Thin Anthropic wrapper. Every caller must tolerate None (no key configured)."""
from __future__ import annotations

import json

from ..config import settings

MODEL = "claude-sonnet-4-5"


def available() -> bool:
    return bool(settings.anthropic_api_key)


async def complete(system: str, user: str, max_tokens: int = 1500) -> str | None:
    if not available():
        return None
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    msg = await client.messages.create(
        model=MODEL, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text


async def complete_json(system: str, user: str, max_tokens: int = 1500) -> dict | list | None:
    text = await complete(system + "\nRespond with JSON only, no prose, no code fences.", user, max_tokens)
    if text is None:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
