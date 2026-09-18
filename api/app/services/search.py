"""Docs-backed use-case search and demo-candidate ranking.

The deterministic ranker is the source of truth. The LLM is only consulted for
queries whose lexical match is weak, which keeps common searches fast and makes
every recommendation explainable from the stored CodeRabbit documentation.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import CandidateScore, PrCandidate, UseCase
from . import llm
from .discovery import anchor_for_use_case

WEAK_THRESHOLD = 70.0
LEXICAL_CONFIDENCE = 42.0
MAX_USE_CASES = 5
MAX_RESULTS = 10

_TOKEN = re.compile(r"[a-z0-9+#.]+")
_STOP_WORDS = {
    "a", "an", "and", "are", "best", "codeabbit", "coderabbit", "demo", "for",
    "find", "i", "in", "is", "it", "me", "most", "of", "on", "or", "pr",
    "pull", "request", "review", "reviewing", "reviews", "show", "that", "the",
    "to", "use", "want", "while", "with",
}

# These are discovery aliases, not product definitions. Product claims still
# come from UseCase.definition and UseCase.doc_url, which are seeded from docs.
CAPABILITY_ALIASES: dict[str, set[str]] = {
    "summarization": {"summary", "summarize", "walkthrough", "overview"},
    "committable-suggestions": {"one-click", "suggestion", "patch", "apply", "fix"},
    "sequence-diagrams": {"diagram", "mermaid", "flow", "sequence"},
    "request-changes": {"approval", "approve", "request", "changes", "resolve"},
    "jira-integration": {"jira", "ticket", "project"},
    "linked-issues": {"acceptance", "criteria", "linked", "issue", "scope"},
    "create-issues": {"create", "follow-up", "issue", "linear"},
    "pipeline-failure": {"ci", "pipeline", "build", "failure", "actions"},
    "docstrings": {"docstring", "documentation", "comments"},
    "unit-tests": {"unit", "tests", "coverage", "generate"},
    "mcp-client": {"mcp", "notion", "confluence", "external", "context", "linear"},
    "pre-merge-checks": {"gate", "policy", "merge", "check", "compliance"},
    "code-guidelines": {"guidelines", "standards", "conventions", "rules"},
    "path-instructions": {"path", "glob", "monorepo", "instructions", "filter"},
    "web-search": {"web", "current", "latest", "cve", "advisory"},
    "planning": {"plan", "implement", "agent", "handoff"},
    "agentic-chat": {"agentic", "chat", "investigate", "performance"},
    "multi-repo": {"multi-repo", "cross-repo", "contract", "dependency", "sdk"},
    "atlas-change-stack": {"change", "stack", "layers", "semantic", "diff"},
    "security-blast-radius": {"blast", "radius", "downstream", "consumer", "impact", "graph"},
    "security-architecture-review": {"architecture", "trust", "boundary", "control", "threat"},
    "security-attack-surface": {"attack", "surface", "entrypoint", "coverage", "drift"},
    "security-deep-scan": {"deep", "scan", "repository", "vulnerability", "secrets", "security"},
}

LANGUAGE_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "python": (".py", ".ipynb"),
    "typescript": (".ts", ".tsx"),
    "javascript": (".js", ".jsx", ".mjs"),
    "go": (".go",),
    "rust": (".rs",),
    "java": (".java",),
    "ruby": (".rb", ".erb"),
    "php": (".php",),
    "terraform": (".tf", ".hcl"),
    "kotlin": (".kt", ".kts"),
    "swift": (".swift",),
    "sql": (".sql",),
}
LANGUAGE_ALIASES = {"js": "javascript", "ts": "typescript", "py": "python", "golang": "go"}


def _tokens(value: str) -> set[str]:
    return {token for token in _TOKEN.findall((value or "").lower())
            if len(token) > 1 and token not in _STOP_WORDS}


def _config_text(value: object, prefix: str = "") -> str:
    if isinstance(value, dict):
        return " ".join(_config_text(item, f"{prefix}.{key}" if prefix else key)
                        for key, item in value.items())
    if isinstance(value, list):
        return " ".join(_config_text(item, prefix) for item in value)
    return f"{prefix} {value}"


def _use_case_fields(use_case: UseCase) -> list[tuple[str, set[str], float]]:
    heuristics = use_case.detection_heuristics or {}
    aliases = CAPABILITY_ALIASES.get(use_case.slug, set())
    return [
        ("name", _tokens(f"{use_case.slug} {use_case.name}"), 5.0),
        ("documented capability", _tokens(use_case.definition or ""), 2.5),
        ("demo guidance", _tokens(use_case.demo_script_notes or ""), 2.0),
        ("detector", _tokens(" ".join(heuristics.get("keywords", []))), 3.5),
        ("configuration", _tokens(_config_text(use_case.required_config or {})), 3.0),
        ("aliases", _tokens(" ".join(aliases)), 4.0),
        ("category", _tokens(use_case.category or ""), 1.5),
    ]


def rank_use_cases(query: str, use_cases: Iterable[UseCase]) -> list[dict]:
    """Rank capabilities against docs-backed fields and explain each match."""
    query_terms = _tokens(query)
    if not query_terms:
        return []

    ranked: list[dict] = []
    query_lower = query.lower()
    for use_case in use_cases:
        matched: dict[str, set[str]] = {}
        term_weights: dict[str, float] = {}
        for label, terms, weight in _use_case_fields(use_case):
            hits = query_terms & terms
            if hits:
                matched[label] = hits
                for term in hits:
                    term_weights[term] = max(term_weights.get(term, 0), weight)
        if not term_weights:
            continue

        coverage = len(term_weights) / len(query_terms)
        strength = sum(term_weights.values()) / (5.0 * len(query_terms))
        phrase = 0.0
        name = (use_case.name or "").lower()
        slug = (use_case.slug or "").replace("-", " ")
        if name in query_lower or slug in query_lower:
            phrase = 20.0
        score = round(min(100.0, 65 * coverage + 25 * strength + phrase), 1)
        reasons = [f"{label}: {', '.join(sorted(hits))}" for label, hits in matched.items()]
        ranked.append({"slug": use_case.slug, "score": score, "reasons": reasons})

    return sorted(ranked, key=lambda item: (-item["score"], item["slug"]))


def _language_intent(query: str) -> tuple[list[str], list[str]]:
    terms = _tokens(query)
    languages: list[str] = []
    for term in terms:
        language = LANGUAGE_ALIASES.get(term, term)
        if language in LANGUAGE_EXTENSIONS and language not in languages:
            languages.append(language)
    explicit_exts = {token for token in terms if token.startswith(".")}
    extensions = set(explicit_exts)
    for language in languages:
        extensions.update(LANGUAGE_EXTENSIONS[language])
    return sorted(languages), sorted(extensions)


async def parse_intent(query: str, use_cases: list[UseCase]) -> dict:
    lexical = rank_use_cases(query, use_cases)
    selected = [item["slug"] for item in lexical[:MAX_USE_CASES]
                if item["score"] >= 18]
    parser = "docs"

    # Clear docs matches avoid an LLM round trip. Ambiguous queries get a
    # constrained second opinion, but only known slugs survive validation.
    if not lexical or lexical[0]["score"] < LEXICAL_CONFIDENCE:
        slugs = [use_case.slug for use_case in use_cases]
        parsed = await llm.complete_json(
            system=("Map a demo request to CodeRabbit capabilities. Return "
                    '{"use_case_slugs": [...]} using only these slugs: '
                    f"{slugs}"),
            user=query,
            max_tokens=220,
        )
        if isinstance(parsed, dict):
            valid = [slug for slug in parsed.get("use_case_slugs", []) if slug in slugs]
            selected = list(dict.fromkeys(valid + selected))[:MAX_USE_CASES]
            parser = "docs+llm" if lexical else "llm"

    languages, file_exts = _language_intent(query)
    score_map = {item["slug"]: item["score"] for item in lexical}
    reason_map = {item["slug"]: item["reasons"] for item in lexical}
    for slug in selected:
        score_map.setdefault(slug, 55.0)
        reason_map.setdefault(slug, ["LLM matched this documented capability"])
    return {
        "use_case_slugs": selected,
        "use_case_scores": score_map,
        "use_case_reasons": reason_map,
        "languages": languages,
        "file_exts": file_exts,
        "keywords": sorted(_tokens(query) - set(languages)),
        "parser": parser,
    }


def _candidate_efficiency(candidate: PrCandidate) -> tuple[float, str]:
    stats = candidate.diff_stats or {}
    files = int(stats.get("files") or len(candidate.files_changed or []))
    lines = int(stats.get("additions") or 0) + int(stats.get("deletions") or 0)
    if files <= 4 and (not lines or lines <= 180):
        return 100.0, "quick"
    if files <= 10 and (not lines or lines <= 600):
        return 82.0, "moderate"
    if files <= 20:
        return 62.0, "involved"
    return 40.0, "large"


def _setup_effort(use_case: UseCase, verified_examples: int) -> str:
    if verified_examples:
        return "ready"
    if use_case.category in {"integrations", "security"}:
        return "setup"
    if use_case.required_config or use_case.category in {"agentic", "generation"}:
        return "configure"
    return "quick"


def _context_match(candidate: PrCandidate, intent: dict) -> tuple[float, list[str]]:
    files = candidate.files_changed or []
    title = (candidate.title or "").lower()
    repo_languages = {str(item).lower() for item in (candidate.repo.languages or [])}
    requested_languages = set(intent.get("languages", []))
    requested_exts = tuple(intent.get("file_exts", []))
    reasons: list[str] = []

    language_match = not requested_languages
    if requested_languages:
        language_match = bool(repo_languages & requested_languages)
        language_match = language_match or any(path.endswith(requested_exts) for path in files)
        if language_match:
            reasons.append("language match")
    if not language_match:
        return 0.0, []

    keywords = intent.get("keywords", [])
    searchable = f"{title} {' '.join(files).lower()}"
    hits = [keyword for keyword in keywords if keyword in searchable]
    if hits:
        reasons.append(f"PR match: {', '.join(hits[:3])}")
    score = 70.0 if not requested_languages else 90.0
    score += min(10.0, 2.5 * len(hits))
    return min(100.0, score), reasons


def _recommendations(use_cases: list[UseCase], intent: dict,
                     rows: list[CandidateScore]) -> list[dict]:
    by_slug: dict[str, list[CandidateScore]] = defaultdict(list)
    for row in rows:
        by_slug[row.use_case.slug].append(row)
    lookup = {use_case.slug: use_case for use_case in use_cases}
    recommendations = []
    for slug in intent.get("use_case_slugs", [])[:MAX_USE_CASES]:
        use_case = lookup.get(slug)
        if not use_case:
            continue
        candidates = by_slug.get(slug, [])
        verified = sum(row.scored_by == "review" for row in candidates)
        best = max((row.score for row in candidates), default=0)
        recommendations.append({
            "slug": slug,
            "name": use_case.name,
            "category": use_case.category,
            "confidence": intent.get("use_case_scores", {}).get(slug, 55.0),
            "why": intent.get("use_case_reasons", {}).get(slug, []),
            "doc_url": use_case.doc_url,
            "demo_notes": use_case.demo_script_notes,
            "required_config": use_case.required_config,
            "candidate_count": len(candidates),
            "verified_examples": verified,
            "best_candidate_score": round(best, 1),
            "effort": _setup_effort(use_case, verified),
        })
    return recommendations


async def search(session: AsyncSession, query: str) -> dict:
    use_cases = (await session.execute(select(UseCase))).scalars().all()
    intent = await parse_intent(query, use_cases)
    use_case_by_slug = {use_case.slug: use_case for use_case in use_cases}
    target_slugs = intent.get("use_case_slugs", [])
    target_ids = [use_case_by_slug[slug].id for slug in target_slugs if slug in use_case_by_slug]

    stmt = (select(CandidateScore)
            .options(selectinload(CandidateScore.candidate).selectinload(PrCandidate.repo),
                     selectinload(CandidateScore.use_case))
            .join(PrCandidate, CandidateScore.pr_candidate_id == PrCandidate.id)
            .where(PrCandidate.state == "open")
            .order_by(CandidateScore.score.desc()).limit(200))
    if target_ids:
        stmt = stmt.where(CandidateScore.use_case_id.in_(target_ids))
    rows = [row for row in (await session.execute(stmt)).scalars().all()
            if row.candidate is not None and row.candidate.repo is not None]

    results = []
    for candidate_score in rows:
        candidate = candidate_score.candidate
        context_score, context_reasons = _context_match(candidate, intent)
        if context_score == 0:
            continue
        relevance = intent.get("use_case_scores", {}).get(candidate_score.use_case.slug, 35.0)
        efficiency, effort = _candidate_efficiency(candidate)
        verified = candidate_score.scored_by == "review"
        score = (0.62 * candidate_score.score + 0.23 * relevance
                 + 0.10 * context_score + 0.05 * efficiency)
        if verified:
            score += 3
        results.append({
            "score": round(min(100.0, score), 1),
            "use_case": candidate_score.use_case.name,
            "use_case_slug": candidate_score.use_case.slug,
            "doc_url": candidate_score.use_case.doc_url,
            "scored_by": candidate_score.scored_by,
            "verified": verified,
            "demo_effort": effort,
            "match_reasons": (intent.get("use_case_reasons", {})
                              .get(candidate_score.use_case.slug, [])[:2] + context_reasons),
            "pr": {
                "candidate_id": candidate.id,
                "title": candidate.title,
                "url": candidate.url,
                "anchor_url": anchor_for_use_case(
                    candidate_score.use_case.slug, candidate.evidence_urls or {}),
                "repo": candidate.repo.full_name,
                "number": candidate.pr_number,
            },
            "rationale": candidate_score.rationale,
        })
    results.sort(key=lambda result: (-result["score"], not result["verified"], result["pr"]["repo"]))
    results = results[:MAX_RESULTS]
    recommendations = _recommendations(use_cases, intent, rows)
    best = results[0]["score"] if results else 0
    return {
        "intent": intent,
        "recommendations": recommendations,
        "results": results,
        "suggest_manufacture": best < WEAK_THRESHOLD,
        "manufacture_hint": (None if best >= WEAK_THRESHOLD else
                             {"use_case_slugs": target_slugs, "query": query}),
    }
