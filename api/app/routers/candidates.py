from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from ..db import SessionLocal, get_session
from ..models import CandidateScore, PrCandidate, Repo, SourceOrg, UseCase
from ..services import github, llm
from ..services.discovery import extract_evidence, run_discovery, score_from_evidence
from ..services.scoring import llm_refine, score_candidate

router = APIRouter(tags=["candidates"])

# In-memory crawl state (single-process; move to DB/redis with arq later)
CRAWL_STATE: dict = {"phase": "idle", "repos_done": 0, "repos_total": 0,
                     "discovered": 0, "backfilled": 0, "error": None, "finished_at": None}


def _set(**kw) -> None:
    CRAWL_STATE.update(kw)


async def _crawl_and_score() -> None:
    from datetime import datetime, timezone
    _set(phase="crawling sources", repos_done=0, repos_total=0,
         discovered=0, backfilled=0, error=None, finished_at=None)
    try:
        await _crawl_inner()
        _set(phase="done", finished_at=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        _set(phase="failed", error=str(exc))


async def _crawl_inner() -> None:
    async with SessionLocal() as session:
        # Layer 1: your Sources repos (curated crawl)
        repos = (await session.execute(
            select(Repo).join(SourceOrg)
            .where(Repo.included, SourceOrg.included,
                   SourceOrg.connection_type.not_in(["discovered", "fixture"])))).scalars().all()
        use_cases = (await session.execute(select(UseCase))).scalars().all()
        _set(repos_total=len(repos))
        for repo in repos:
            _set(repos_done=CRAWL_STATE["repos_done"] + 1)
            try:
                prs = await github.list_open_prs(repo.full_name)
            except Exception:
                continue  # token missing / rate limit — skip repo, keep going
            # clear this repo's old candidates + their scores, but never flagged keepers
            from ..models import Example
            keep = select(Example.pr_candidate_id)
            stale = select(PrCandidate.id).where(
                PrCandidate.repo_id == repo.id, PrCandidate.id.not_in(keep))
            await session.execute(delete(CandidateScore)
                                  .where(CandidateScore.pr_candidate_id.in_(stale)))
            await session.execute(delete(PrCandidate).where(
                PrCandidate.repo_id == repo.id, PrCandidate.id.not_in(keep)))
            for pr in prs:
                dup = (await session.execute(
                    select(PrCandidate.id).where(PrCandidate.repo_id == repo.id,
                                                 PrCandidate.pr_number == pr["pr_number"]))).first()
                if dup:
                    from ..services.discovery import backfill_candidate
                    kept = await session.get(PrCandidate, dup[0])
                    if kept:
                        await backfill_candidate(session, kept, repo.full_name, use_cases)
                    continue  # flagged keeper survived the sweep — don't duplicate it
                cand = PrCandidate(repo_id=repo.id, **pr)
                session.add(cand)
                await session.flush()
                # evidence first: if the bot already reviewed this PR, parse its output
                evidence = set()
                try:
                    snap = await github.get_pr_snapshot(repo.full_name, cand.pr_number)
                    evidence = extract_evidence(snap["bot_review_text"])
                    from ..services.discovery import evidence_anchors
                    cand.evidence_urls = evidence_anchors(snap.get("bot_comments", []))
                except Exception:
                    pass
                for uc in use_cases:
                    scored = score_from_evidence(evidence, uc) if evidence else None
                    if scored:
                        session.add(CandidateScore(pr_candidate_id=cand.id, use_case_id=uc.id,
                                                   score=scored[0], rationale=scored[1],
                                                   scored_by="review"))
                        continue
                    score, rationale = score_candidate(cand, uc, stars=repo.stars)
                    if score >= 60 and llm.available():
                        refined = await llm_refine(cand, uc, score)
                        if refined:
                            score, rationale = refined
                            session.add(CandidateScore(pr_candidate_id=cand.id, use_case_id=uc.id,
                                                       score=score, rationale=rationale, scored_by="llm"))
                            continue
                    if score > 0:
                        session.add(CandidateScore(pr_candidate_id=cand.id, use_case_id=uc.id,
                                                   score=score, rationale=rationale))
            await session.commit()

        # Layer 2: GitHub-wide discovery of bot-reviewed open PRs
        if settings.discovery_enabled and settings.github_token:
            _set(phase="discovering on GitHub")
            _set(discovered=await run_discovery(session))

        # Layer 3: sweep — backfill anchors for any candidate that predates them
        if settings.github_token:
            _set(phase="backfilling anchors")
            from ..services.discovery import backfill_candidate
            stale = (await session.execute(
                select(PrCandidate).options(selectinload(PrCandidate.repo))
                .where(PrCandidate.evidence_urls.is_(None) | (PrCandidate.evidence_urls == {}))
                .limit(40))).scalars().all()
            for cand in stale:
                await backfill_candidate(session, cand, cand.repo.full_name, use_cases)
                _set(backfilled=CRAWL_STATE["backfilled"] + 1)
            await session.commit()


@router.post("/crawl", status_code=202)
async def crawl(background: BackgroundTasks):
    if CRAWL_STATE["phase"] not in ("idle", "done", "failed"):
        return {"status": "already running", **CRAWL_STATE}
    background.add_task(_crawl_and_score)
    return {"status": "crawl started"}


@router.get("/crawl/status")
async def crawl_status():
    return CRAWL_STATE


@router.get("/candidates")
async def list_candidates(use_case: str | None = None, min_score: float = 0,
                          session: AsyncSession = Depends(get_session)):
    stmt = (select(CandidateScore)
            .options(selectinload(CandidateScore.candidate).selectinload(PrCandidate.repo),
                     selectinload(CandidateScore.use_case))
            .where(CandidateScore.score >= min_score)
            .order_by(CandidateScore.score.desc()).limit(100))
    if use_case:
        stmt = stmt.join(UseCase, CandidateScore.use_case_id == UseCase.id).where(UseCase.slug == use_case)
    rows = [cs for cs in (await session.execute(stmt)).scalars().all()
            if cs.candidate is not None and cs.candidate.repo is not None]
    from ..models import Example
    flagged = {(e.pr_candidate_id, e.use_case_id) for e in
               (await session.execute(select(Example).where(Example.status == "approved"))).scalars()}
    from ..services.discovery import anchor_for_use_case
    return [{
        "flagged": (cs.pr_candidate_id, cs.use_case_id) in flagged,
        "candidate_id": cs.pr_candidate_id, "score": cs.score, "rationale": cs.rationale,
        "scored_by": cs.scored_by, "use_case": cs.use_case.slug,
        "pr": {"number": cs.candidate.pr_number, "title": cs.candidate.title,
               "url": cs.candidate.url, "repo": cs.candidate.repo.full_name,
               "files": cs.candidate.files_changed, "stats": cs.candidate.diff_stats,
               # deep link to the exact bot comment proving this use case, when we have it
               "anchor_url": anchor_for_use_case(cs.use_case.slug, cs.candidate.evidence_urls or {})},
    } for cs in rows]


@router.get("/candidates/{candidate_id}")
async def candidate_detail(candidate_id: int, session: AsyncSession = Depends(get_session)):
    """Drilldown: every finding in CodeRabbit's review (with its exact-comment
    anchor) plus every use case this PR scores for."""
    cand = (await session.execute(
        select(PrCandidate)
        .options(selectinload(PrCandidate.repo),
                 selectinload(PrCandidate.scores).selectinload(CandidateScore.use_case))
        .where(PrCandidate.id == candidate_id))).scalar_one_or_none()
    if not cand:
        raise HTTPException(404)
    from ..services.discovery import SIGNATURES
    anchors = cand.evidence_urls or {}
    # which use cases does each finding prove?
    finding_to_ucs: dict[str, list[str]] = {}
    for slug, (_, keys) in SIGNATURES.items():
        for k in keys:
            finding_to_ucs.setdefault(k, []).append(slug)
    return {
        "pr": {"number": cand.pr_number, "title": cand.title, "url": cand.url,
               "repo": cand.repo.full_name, "files": cand.files_changed,
               "stats": cand.diff_stats},
        "findings": [{"key": k, "label": k.replace("_", " "), "comment_url": url,
                      "proves": finding_to_ucs.get(k, [])}
                     for k, url in anchors.items()],
        "scores": sorted([{"use_case": s.use_case.slug, "use_case_name": s.use_case.name,
                           "score": s.score, "scored_by": s.scored_by, "rationale": s.rationale}
                          for s in cand.scores], key=lambda x: -x["score"]),
    }


@router.get("/candidates/{candidate_id}/export")
async def export_candidate(candidate_id: int, use_case: str,
                           session: AsyncSession = Depends(get_session)):
    cand = (await session.execute(
        select(PrCandidate).options(selectinload(PrCandidate.repo), selectinload(PrCandidate.scores))
        .where(PrCandidate.id == candidate_id))).scalar_one_or_none()
    if not cand:
        raise HTTPException(404)
    uc = (await session.execute(select(UseCase).where(UseCase.slug == use_case))).scalar_one_or_none()
    if not uc:
        raise HTTPException(404, "unknown use case")
    from ..services.discovery import anchor_for_use_case
    anchor = anchor_for_use_case(uc.slug, cand.evidence_urls or {})
    return {
        "url": cand.url,
        "anchor_url": anchor,
        "repo": cand.repo.full_name,
        "use_case": uc.name,
        "talk_track": uc.demo_script_notes,
        "config_needed": uc.required_config,
        "markdown": (f"### Demo: {uc.name}\n- PR: {cand.url}"
                     + (f"\n- Exact comment: {anchor}" if anchor else "")
                     + "\n- Why: "
                     + next((s.rationale for s in cand.scores if s.use_case_id == uc.id), "")
                     + f"\n- Config: `{uc.required_config}`"),
    }
