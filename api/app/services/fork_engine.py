"""Manufacture pipeline: rank forkable repos, generate the change + config,
execute fork → commit → open PR."""
from __future__ import annotations

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Repo, UseCase
from . import llm
from .config_engine.resolver import fill_gaps
from .config_engine.schema_defaults import SCHEMA_DEFAULTS


def rank_forkable_repos(repos: list[Repo], uc: UseCase) -> list[tuple[Repo, float, str]]:
    exts = (uc.detection_heuristics or {}).get("file_exts") or []
    lang_hint = {e.strip("."): 1 for e in exts}
    ranked = []
    for r in repos:
        if not r.forkable or not r.included:
            continue
        score, why = 50.0, []
        langs = [str(l).lower() for l in (r.languages or [])]
        if lang_hint and any(l in lang_hint or l[:2] in ("py", "ts", "go") and f".{l[:2]}" in exts for l in langs):
            score += 20; why.append(f"language fit ({', '.join(langs)})")
        if not r.has_coderabbit:
            score += 15; why.append("no existing .coderabbit.yaml to conflict")
        else:
            score -= 20; why.append("already has CodeRabbit config")
        if 10 <= r.stars:
            score += 10; why.append("realistic, active project")
        ranked.append((r, score, "; ".join(why) or "eligible fork target"))
    return sorted(ranked, key=lambda t: -t[1])


def _config_from_required(uc: UseCase) -> str:
    """Deterministic fallback: expand dotted required_config keys into yaml,
    validated by filling against schema defaults (resolution-valid by construction)."""
    nested: dict = {}
    for dotted, value in (uc.required_config or {}).items():
        cur = nested
        parts = dotted.split(".")
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = value
    fill_gaps(nested, SCHEMA_DEFAULTS)  # raises nothing; sanity that shapes align
    header = f"# Generated for use case: {uc.name}\n# Each key below is required to trigger the behavior.\n"
    return header + yaml.safe_dump(nested, sort_keys=False) if nested else header + "{}\n"


async def generate_suggestion(session: AsyncSession, uc: UseCase,
                              extra_context: str = "", config_kind: str = "yaml") -> dict:
    repos = (await session.execute(select(Repo))).scalars().all()
    ranked = rank_forkable_repos(repos, uc)
    if not ranked:
        return {"error": "No forkable repos in your included sources — connect one in Sources."}
    base, _, rationale = ranked[0]

    suggested_changes: list[dict] = []
    suggested_config = _config_from_required(uc)

    generated = await llm.complete_json(
        system=("You design a minimal file change for a forked repo that will make CodeRabbit "
                "demonstrate a specific capability when the PR is reviewed. Return "
                '{"changes": [{"path": str, "description": str, "content": str}], '
                '"config_yaml": str, "config_ts": str, "rationale": str}. '
                "config_ts is a .coderabbit/review.ts custom-methods file, only if the capability needs it."),
        user=(f"Capability: {uc.name}\nNotes: {uc.demo_script_notes}\n"
              f"Required config keys: {uc.required_config}\n"
              f"Base repo: {base.full_name} (langs: {base.languages})\n"
              f"Extra context from user: {extra_context or 'none'}"),
        max_tokens=2500,
    )
    if isinstance(generated, dict):
        suggested_changes = generated.get("changes") or []
        if config_kind == "ts" and generated.get("config_ts"):
            suggested_config = generated["config_ts"]
        elif generated.get("config_yaml"):
            suggested_config = generated["config_yaml"]
        rationale = generated.get("rationale") or rationale
    else:
        # No-LLM fallback: a marker file exercising the required config
        exts = (uc.detection_heuristics or {}).get("file_exts") or [".py"]
        suggested_changes = [{
            "path": f"demo/{uc.slug}_example{exts[0]}",
            "description": f"Seed file crafted to trigger '{uc.name}' in review — edit to taste.",
            "content": f"# Demo seed for CodeRabbit use case: {uc.name}\n"
                       f"# {uc.demo_script_notes}\n\n"
                       "def process(items):\n    # TODO: intentionally missing docstring & tests\n"
                       "    return [i for i in items if i]\n",
        }]

    return {
        "base_repo_id": base.id,
        "base_repo_full_name": base.full_name,
        "rationale": rationale,
        "suggested_changes": suggested_changes,
        "suggested_config": suggested_config,
        "config_kind": config_kind,
        "alternatives": [{"repo": r.full_name, "score": s, "why": w} for r, s, w in ranked[1:4]],
    }
