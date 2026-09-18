"""GitHub-wide discovery: hunt open PRs that CodeRabbit has already reviewed,
score them by what's actually in the bot's review (evidence over prediction)."""
from __future__ import annotations

import asyncio
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import CandidateScore, PrCandidate, Repo, SourceOrg, UseCase
from . import github

# Evidence extractors: key -> regex over the bot's combined review text
EVIDENCE_PATTERNS: dict[str, re.Pattern] = {
    "walkthrough": re.compile(r"#+\s*Walkthrough", re.I),
    "sequence_diagram": re.compile(r"sequenceDiagram", re.I),
    "committable": re.compile(r"Committable suggestion|```suggestion", re.I),
    "linked_issues": re.compile(r"Assessment against linked issues", re.I),
    "pre_merge": re.compile(r"Pre-merge checks", re.I),
    "related_prs": re.compile(r"(Possibly related|Related) PRs", re.I),
    "related_issues": re.compile(r"(Possibly related|Related) issues", re.I),
    "suggested_reviewers": re.compile(r"Suggested reviewers", re.I),
    "tools": re.compile(r"\b(Ruff|Biome|Semgrep|markdownlint|golangci-lint|Shellcheck|actionlint|LanguageTool|Gitleaks|Checkov|Hadolint)\b"),
    "docstrings": re.compile(r"docstring", re.I),
    "unit_tests": re.compile(r"unit test", re.I),
    "learnings": re.compile(r"learnings?", re.I),
    "pipeline_failure": re.compile(r"(pipeline|check).{0,30}fail", re.I),
}

# use-case slug -> (search phrase for GitHub `in:comments`, evidence keys that prove it)
SIGNATURES: dict[str, tuple[str | None, list[str]]] = {
    "summarization": ("Walkthrough", ["walkthrough"]),
    "sequence-diagrams": ("sequenceDiagram", ["sequence_diagram"]),
    "committable-suggestions": ("Committable suggestion", ["committable"]),
    "linked-issues": ("Assessment against linked issues", ["linked_issues"]),
    "pre-merge-checks": ("Pre-merge checks", ["pre_merge"]),
    "related-prs": ("Possibly related PRs", ["related_prs"]),
    "related-issues": ("Possibly related issues", ["related_issues"]),
    "suggested-reviewers": ("Suggested reviewers", ["suggested_reviewers"]),
    "tools": (None, ["tools"]),                      # piggybacks on other searches
    "docstrings": (None, ["docstrings"]),
    "unit-tests": (None, ["unit_tests"]),
    "learnings": (None, ["learnings"]),
    "pipeline-failure": (None, ["pipeline_failure"]),
}

EVIDENCE_LABELS: dict[str, str] = {
    "walkthrough": "a CodeRabbit Walkthrough",
    "sequence_diagram": "a generated sequence diagram",
    "committable": "a committable suggestion",
    "linked_issues": "an assessment against linked issues",
    "pre_merge": "pre-merge check results",
    "related_prs": "related pull requests",
    "related_issues": "related issues",
    "suggested_reviewers": "suggested reviewers",
    "tools": "linter or security-tool findings",
    "docstrings": "docstring generation guidance",
    "unit_tests": "unit-test generation guidance",
    "learnings": "team learnings",
    "pipeline_failure": "pipeline-failure analysis",
}


def extract_evidence(bot_text: str) -> set[str]:
    return {key for key, pat in EVIDENCE_PATTERNS.items() if pat.search(bot_text or "")}


def evidence_anchors(bot_comments: list[dict]) -> dict[str, str]:
    """evidence key -> html_url of the first bot comment proving it — the deep
    link that lands you on the exact comment, not just the PR."""
    anchors: dict[str, str] = {}
    for c in bot_comments or []:
        for key, pat in EVIDENCE_PATTERNS.items():
            if key not in anchors and c.get("url") and pat.search(c.get("body") or ""):
                anchors[key] = c["url"]
    return anchors


def anchor_for_use_case(slug: str, anchors: dict[str, str]) -> str | None:
    sig = SIGNATURES.get(slug)
    if not sig:
        return None
    return next((anchors[k] for k in sig[1] if k in anchors), None)


def evidence_for_use_case(slug: str, anchors: dict[str, str]) -> list[str]:
    """Human-readable, capability-specific evidence present in a live review."""
    sig = SIGNATURES.get(slug)
    if not sig:
        return []
    return [EVIDENCE_LABELS[key] for key in sig[1] if key in anchors]


def score_from_evidence(evidence: set[str], uc: UseCase) -> tuple[float, str] | None:
    """Evidence-based score for one use case, or None if it has no signature."""
    sig = SIGNATURES.get(uc.slug)
    if not sig:
        return None
    _, keys = sig
    hits = [k for k in keys if k in evidence]
    if not hits:
        return None
    breadth = min(13, 3 * len(evidence))  # richer reviews demo better
    score = min(98.0, 85.0 + breadth)
    pretty = ", ".join(h.replace("_", " ") for h in hits)
    return score, f"CodeRabbit's live review contains {pretty} (verified, not predicted); {len(evidence)} capabilities visible on this PR"


async def _ensure_repo(session: AsyncSession, full_name: str) -> Repo | None:
    owner = full_name.split("/")[0]
    if owner.lower() in settings.excluded_orgs:
        return None
    repo = (await session.execute(
        select(Repo).where(Repo.full_name == full_name))).scalar_one_or_none()
    if repo:
        # This path is reached from a GitHub search for CodeRabbit bot comments,
        # which is stronger installation evidence than stale repository metadata.
        repo.has_coderabbit = True
        return repo
    org = (await session.execute(
        select(SourceOrg).where(SourceOrg.org_name == owner,
                                SourceOrg.connection_type == "discovered"))).scalar_one_or_none()
    if not org:
        org = SourceOrg(org_name=owner, connection_type="discovered")
        session.add(org)
        await session.flush()
    repo = Repo(source_org_id=org.id, full_name=full_name, has_coderabbit=True)
    session.add(repo)
    await session.flush()
    return repo


async def backfill_candidate(session: AsyncSession, cand: PrCandidate, full_name: str,
                             use_cases: list[UseCase]) -> None:
    """Fetch the bot's comments for an existing candidate that predates anchor
    capture: store the deep-link anchors and upgrade its scores to evidence-based."""
    if cand.evidence_urls:
        return
    try:
        snap = await github.get_pr_snapshot(full_name, cand.pr_number)
    except Exception:
        return
    cand.evidence_urls = evidence_anchors(snap.get("bot_comments", []))
    evidence = extract_evidence(snap["bot_review_text"])
    if not evidence:
        return
    existing = {s.use_case_id: s for s in (await session.execute(
        select(CandidateScore).where(CandidateScore.pr_candidate_id == cand.id))).scalars()}
    for uc in use_cases:
        scored = score_from_evidence(evidence, uc)
        if not scored:
            continue
        row = existing.get(uc.id)
        if row:
            row.score, row.rationale, row.scored_by = scored[0], scored[1], "review"
        else:
            session.add(CandidateScore(pr_candidate_id=cand.id, use_case_id=uc.id,
                                       score=scored[0], rationale=scored[1], scored_by="review"))


async def run_discovery(session: AsyncSession) -> int:
    """One discovery pass. Returns number of PRs ingested."""
    use_cases = {uc.slug: uc for uc in
                 (await session.execute(select(UseCase))).scalars().all()}
    ingested = 0
    for slug, (phrase, _) in SIGNATURES.items():
        if phrase is None or slug not in use_cases:
            continue
        try:
            found = await github.search_bot_reviewed_prs(phrase, settings.discovery_per_use_case)
        except Exception:
            await asyncio.sleep(2)
            continue
        for hit in found:
            repo = await _ensure_repo(session, hit["full_name"])
            if repo is None or not repo.included:
                continue
            exists = (await session.execute(
                select(PrCandidate).where(PrCandidate.repo_id == repo.id,
                                          PrCandidate.pr_number == hit["pr_number"]))).scalar_one_or_none()
            if exists:
                await backfill_candidate(session, exists, hit["full_name"],
                                         list(use_cases.values()))
                continue
            try:
                snap = await github.get_pr_snapshot(hit["full_name"], hit["pr_number"])
            except Exception:
                continue
            anchors = evidence_anchors(snap.get("bot_comments", []))
            cand = PrCandidate(repo_id=repo.id, pr_number=hit["pr_number"], title=hit["title"],
                               url=hit["url"], files_changed=snap["files_changed"],
                               diff_stats=snap["diff_stats"], evidence_urls=anchors)
            session.add(cand)
            await session.flush()
            evidence = extract_evidence(snap["bot_review_text"])
            for uc in use_cases.values():
                scored = score_from_evidence(evidence, uc)
                if scored:
                    session.add(CandidateScore(pr_candidate_id=cand.id, use_case_id=uc.id,
                                               score=scored[0], rationale=scored[1],
                                               scored_by="review"))
            ingested += 1
        await session.commit()
        await asyncio.sleep(2)  # stay under the 30 searches/min limit
    return ingested
