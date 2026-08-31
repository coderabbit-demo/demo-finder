from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import CandidateScore, Example, UseCase
from ..services import llm

router = APIRouter(prefix="/use-cases", tags=["use-cases"])
GOOD = 70


@router.get("")
async def list_use_cases(session: AsyncSession = Depends(get_session)):
    ucs = (await session.execute(select(UseCase))).scalars().all()
    counts = dict((await session.execute(
        select(CandidateScore.use_case_id, func.count())
        .where(CandidateScore.score >= GOOD).group_by(CandidateScore.use_case_id))).all())
    flagged = dict((await session.execute(
        select(Example.use_case_id, func.count())
        .where(Example.status == "approved").group_by(Example.use_case_id))).all())
    return [{
        "flagged_count": flagged.get(u.id, 0),
        "id": u.id, "slug": u.slug, "name": u.name, "category": u.category,
        "is_custom": u.is_custom, "demo_script_notes": u.demo_script_notes,
        "definition": u.definition, "doc_url": u.doc_url,
        "detection_heuristics": u.detection_heuristics,
        "required_config": u.required_config,
        "good_candidates": counts.get(u.id, 0),
    } for u in ucs]


class PromptIn(BaseModel):
    prompt: str


@router.post("/from-prompt")
async def create_from_prompt(body: PromptIn, session: AsyncSession = Depends(get_session)):
    generated = await llm.complete_json(
        system=("Convert a described CodeRabbit demo use case into "
                '{"slug": kebab, "name": str, "category": str, '
                '"detection_heuristics": {"keywords": [...], "file_exts": [...], "min_files": int?}, '
                '"required_config": {dotted.key: value}, "demo_script_notes": str}'),
        user=body.prompt, max_tokens=600,
    )
    if not isinstance(generated, dict) or "slug" not in generated:
        # deterministic fallback: keyword heuristics from the prompt itself
        words = [w.strip(".,").lower() for w in body.prompt.split() if len(w) > 4][:6]
        slug = "-".join(words[:3]) or "custom-use-case"
        generated = {"slug": slug, "name": body.prompt[:80].title(), "category": "custom",
                     "detection_heuristics": {"keywords": words},
                     "required_config": {}, "demo_script_notes": body.prompt}
    if (await session.execute(select(UseCase).where(UseCase.slug == generated["slug"]))).first():
        raise HTTPException(409, f"use case '{generated['slug']}' already exists")
    uc = UseCase(**generated, is_custom=True, created_from_prompt=body.prompt)
    session.add(uc)
    await session.commit()
    return {"id": uc.id, "slug": uc.slug, "name": uc.name}
