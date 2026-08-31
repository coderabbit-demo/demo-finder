"""NL example search: LLM intent parsing when available, keyword fallback,
ranked against scored candidates. Weak results pivot to Manufacture."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CandidateScore, PrCandidate, UseCase
from . import llm

WEAK_THRESHOLD = 70.0


async def parse_intent(query: str, use_cases: list[UseCase]) -> dict:
    slugs = [uc.slug for uc in use_cases]
    parsed = await llm.complete_json(
        system=("Parse a demo-example search query. Return "
                '{"use_case_slugs": [...], "languages": [...], "file_exts": [...], "keywords": [...]}'
                f". Valid slugs: {slugs}"),
        user=query, max_tokens=300,
    )
    if isinstance(parsed, dict):
        parsed["parser"] = "llm"
        return parsed
    # keyword fallback
    q = query.lower()
    matched = [uc.slug for uc in use_cases
               if any(w in q for w in uc.name.lower().split()) and len(uc.name) > 3]
    return {"use_case_slugs": matched, "languages": [], "file_exts": [],
            "keywords": [w for w in q.split() if len(w) > 3], "parser": "keyword"}


async def search(session: AsyncSession, query: str) -> dict:
    use_cases = (await session.execute(select(UseCase))).scalars().all()
    intent = await parse_intent(query, use_cases)
    slug_ids = {uc.slug: uc.id for uc in use_cases}
    target_ids = [slug_ids[s] for s in intent.get("use_case_slugs", []) if s in slug_ids]

    stmt = (select(CandidateScore)
            .options(selectinload(CandidateScore.candidate).selectinload(PrCandidate.repo),
                     selectinload(CandidateScore.use_case))
            .order_by(CandidateScore.score.desc()).limit(50))
    if target_ids:
        stmt = stmt.where(CandidateScore.use_case_id.in_(target_ids))
    rows = (await session.execute(stmt)).scalars().all()

    kws = [k.lower() for k in intent.get("keywords", [])]
    exts = intent.get("file_exts", [])
    results = []
    for cs in rows:
        cand = cs.candidate
        boost = 0.0
        text = f"{cand.title} {' '.join(cand.files_changed or [])}".lower()
        boost += sum(4 for k in kws if k in text)
        if exts and any(f.endswith(tuple(exts)) for f in (cand.files_changed or [])):
            boost += 10
        results.append({
            "score": round(min(100, cs.score + boost), 1),
            "use_case": cs.use_case.name,
            "pr": {"title": cand.title, "url": cand.url, "repo": cand.repo.full_name,
                   "number": cand.pr_number},
            "rationale": cs.rationale,
        })
    results.sort(key=lambda r: -r["score"])
    results = results[:10]
    best = results[0]["score"] if results else 0
    return {
        "intent": intent,
        "results": results,
        "suggest_manufacture": best < WEAK_THRESHOLD,
        "manufacture_hint": (None if best >= WEAK_THRESHOLD else
                             {"use_case_slugs": intent.get("use_case_slugs", []), "query": query}),
    }
