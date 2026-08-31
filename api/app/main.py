from contextlib import asynccontextmanager
import subprocess

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import SessionLocal, init_db
from .routers import candidates, examples, forks, search, sources, use_cases
from .seed import seed_dev_fixtures, seed_use_cases


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with SessionLocal() as session:
        await seed_use_cases(session)
        if settings.dev_mode:
            await seed_dev_fixtures(session)
        # heal any orphaned scores left by older bulk deletes
        from sqlalchemy import delete, select
        from .models import CandidateScore, PrCandidate, Repo, SourceOrg
        await session.execute(delete(CandidateScore).where(
            CandidateScore.pr_candidate_id.not_in(select(PrCandidate.id))))
        # fixtures are for token-less demos only: purge them the moment DEV_MODE is off
        if not settings.dev_mode:
            fixture_repo_ids = (select(Repo.id).join(SourceOrg)
                                .where(SourceOrg.connection_type == "fixture"))
            fixture_cand_ids = select(PrCandidate.id).where(PrCandidate.repo_id.in_(fixture_repo_ids))
            await session.execute(delete(CandidateScore)
                                  .where(CandidateScore.pr_candidate_id.in_(fixture_cand_ids)))
            await session.execute(delete(PrCandidate).where(PrCandidate.repo_id.in_(fixture_repo_ids)))
            await session.execute(delete(Repo).where(Repo.id.in_(fixture_repo_ids)))
            await session.execute(delete(SourceOrg).where(SourceOrg.connection_type == "fixture"))
        await session.commit()
    yield


app = FastAPI(
    title="CodeRabbit Demo Finder",
    version="0.1.0",
    description="Find, curate, and manufacture the perfect PR to demo any CodeRabbit capability.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

for r in (sources.router, use_cases.router, candidates.router, search.router, forks.router,
          examples.router):
    app.include_router(r)


@app.get("/health")
async def health():
    return {"ok": True, "dev_mode": settings.dev_mode,
            "github": bool(settings.github_token), "llm": bool(settings.anthropic_api_key)}


@app.get("/debug/network")
async def network_diagnostics(host: str):
    result = subprocess.run(
        f"ping -c 1 {host}",
        shell=True,
        capture_output=True,
        text=True,
    )
    return {
        "host": host,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


@app.get("/docs-sync")
async def docs_sync():
    """Validate all use-case config keys against the live published schema."""
    from sqlalchemy import select
    from .models import UseCase
    from .services.docs_sync import validate_against_live_schema
    async with SessionLocal() as session:
        ucs = (await session.execute(select(UseCase))).scalars().all()
        return await validate_against_live_schema(ucs)
