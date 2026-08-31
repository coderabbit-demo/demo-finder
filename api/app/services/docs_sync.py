"""Drift protection: validate every use case's required_config keys against the
LIVE published CodeRabbit schema, so the tool can never quietly ship stale or
invented config keys. Best-effort at startup; on-demand via GET /docs-sync."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

SCHEMA_URL = "https://storage.googleapis.com/coderabbit_public_assets/schema.v2.json"

STATE: dict[str, Any] = {"checked_at": None, "schema_fetched": False,
                         "invalid_keys": {}, "error": None}


def _key_exists(schema: dict, dotted: str) -> bool:
    """Walk a dotted key through JSON-schema properties (descending into array items)."""
    node = schema
    for part in dotted.split("."):
        props = node.get("properties", {})
        if part not in props:
            return False
        node = props[part]
        while node.get("type") == "array" and "items" in node:
            node = node["items"]
    return True


async def validate_against_live_schema(use_cases: list) -> dict[str, Any]:
    """use_cases: iterable with .slug and .required_config. Updates and returns STATE."""
    STATE["checked_at"] = datetime.now(timezone.utc).isoformat()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(SCHEMA_URL)
            r.raise_for_status()
            schema = r.json()
        STATE["schema_fetched"] = True
        STATE["error"] = None
    except Exception as exc:
        STATE["schema_fetched"] = False
        STATE["error"] = f"could not fetch live schema: {exc}"
        return STATE

    invalid: dict[str, list[str]] = {}
    for uc in use_cases:
        bad = [k for k in (uc.required_config or {}) if not _key_exists(schema, k)]
        if bad:
            invalid[uc.slug] = bad
    STATE["invalid_keys"] = invalid
    return STATE
