from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db import get_session
from ..models import Example, PrCandidate, UseCase

router = APIRouter(prefix="/examples", tags=["examples"])


class FlagIn(BaseModel):
    candidate_id: int
    use_case_slug: str
    demo_notes: str = ""


@router.post("")
async def flag(body: FlagIn, session: AsyncSession = Depends(get_session)):
    uc = (await session.execute(
        select(UseCase).where(UseCase.slug == body.use_case_slug))).scalar_one_or_none()
    if not uc:
        raise HTTPException(404, "unknown use case")
    existing = (await session.execute(
        select(Example).where(Example.pr_candidate_id == body.candidate_id,
                              Example.use_case_id == uc.id))).scalar_one_or_none()
    if existing:  # toggle off
        await session.delete(existing)
        await session.commit()
        return {"flagged": False}
    ex = Example(use_case_id=uc.id, pr_candidate_id=body.candidate_id,
                 status="approved", demo_notes=body.demo_notes)
    session.add(ex)
    await session.commit()
    return {"flagged": True, "id": ex.id}


@router.get("")
async def list_examples(use_case: str | None = None,
                        session: AsyncSession = Depends(get_session)):
    stmt = (select(Example)
            .options(selectinload(Example.use_case),
                     selectinload(Example.candidate).selectinload(PrCandidate.repo))
            .where(Example.status == "approved"))
    if use_case:
        stmt = stmt.join(UseCase, Example.use_case_id == UseCase.id).where(UseCase.slug == use_case)
    rows = (await session.execute(stmt)).scalars().all()
    return [{
        "id": e.id, "use_case": e.use_case.slug, "demo_notes": e.demo_notes,
        "candidate_id": e.pr_candidate_id,
        "pr": {"title": e.candidate.title, "url": e.candidate.url,
               "repo": e.candidate.repo.full_name, "number": e.candidate.pr_number},
    } for e in rows]
