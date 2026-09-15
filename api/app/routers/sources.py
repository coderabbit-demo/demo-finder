from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from ..db import get_session
from ..models import PrCandidate, Repo, SourceOrg

router = APIRouter(prefix="/sources", tags=["sources"])


class OrgIn(BaseModel):
    provider: str = "github"
    org_name: str
    connection_type: str = "oss"
    repos: list[str] = []


@router.get("/config-preview")
async def preview_config(filename: str):
    """Return a generated config artifact for browser preview."""
    config_path = Path(settings.config_export_dir) / filename
    if not config_path.is_file():
        raise HTTPException(404, "config artifact not found")
    return FileResponse(config_path, media_type="application/x-yaml")


@router.get("/orgs")
async def list_orgs(session: AsyncSession = Depends(get_session)):
    orgs = (await session.execute(
        select(SourceOrg).options(selectinload(SourceOrg.repos)))).scalars().all()
    return [{
        "id": o.id, "org_name": o.org_name, "provider": o.provider,
        "connection_type": o.connection_type, "included": o.included,
        "repos": [{"id": r.id, "full_name": r.full_name, "included": r.included,
                   "languages": r.languages, "stars": r.stars,
                   "has_coderabbit": r.has_coderabbit} for r in o.repos],
    } for o in orgs]


@router.post("/orgs")
async def add_org(body: OrgIn, session: AsyncSession = Depends(get_session)):
    if body.org_name.lower() in settings.excluded_orgs:
        raise HTTPException(400, f"'{body.org_name}' is permanently excluded")
    discovered: list[dict] = []
    if not body.repos:
        from ..services import github
        try:
            discovered = await github.list_org_repos(body.org_name)
        except RuntimeError as exc:  # no token
            raise HTTPException(422, str(exc))
        except Exception as exc:
            raise HTTPException(502, f"GitHub lookup for '{body.org_name}' failed: {exc}")
        if not discovered:
            raise HTTPException(404, f"no repos found for '{body.org_name}'")
    org = SourceOrg(provider=body.provider, org_name=body.org_name,
                    connection_type=body.connection_type)
    session.add(org)
    await session.flush()
    for full_name in body.repos:
        session.add(Repo(source_org_id=org.id, full_name=full_name, provider=body.provider))
    for meta in discovered:
        session.add(Repo(source_org_id=org.id, provider=body.provider, **meta))
    await session.commit()
    return {"id": org.id, "repos_discovered": len(discovered)}


@router.delete("/orgs/{org_id}")
async def delete_org(org_id: int, session: AsyncSession = Depends(get_session)):
    org = (await session.execute(
        select(SourceOrg).options(
            selectinload(SourceOrg.repos).selectinload(Repo.candidates)
            .selectinload(PrCandidate.scores))
        .where(SourceOrg.id == org_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(404)
    await session.delete(org)
    await session.commit()
    return {"ok": True}


@router.patch("/orgs/{org_id}")
async def toggle_org(org_id: int, included: bool, session: AsyncSession = Depends(get_session)):
    org = await session.get(SourceOrg, org_id)
    if not org:
        raise HTTPException(404)
    org.included = included
    await session.commit()
    return {"ok": True}


@router.patch("/repos/{repo_id}")
async def toggle_repo(repo_id: int, included: bool, session: AsyncSession = Depends(get_session)):
    repo = await session.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404)
    repo.included = included
    await session.commit()
    return {"ok": True}
