# CodeRabbit Demo Finder (v1)

Find, curate, and manufacture the perfect PR to demo any CodeRabbit capability.
See `design/VISION.md` for the approved spec and `design/mockup.html` for the original vision.
The frontend and API can also be started independently during local development.

## Quick start (no docker, SQLite)

```bash
# backend
cd api
python3 -m venv .venv && source .venv/bin/activate   # once; later just `source .venv/bin/activate`
pip install -r requirements.txt
DEV_MODE=true uvicorn app.main:app --reload        # http://localhost:8000/docs

# frontend
cd web && npm install && npm run dev               # http://localhost:5173
```

`DEV_MODE=true` seeds sample repos/PRs/scores so the UI works with zero tokens.
Set `GITHUB_TOKEN` for real crawling/forking, `ANTHROPIC_API_KEY` for LLM
scoring, NL search intent parsing, and change/config generation (heuristic
fallbacks run without it).

## Docker (Postgres)

```bash
cp .env.example .env   # fill in tokens
docker compose up
```

## Layout

- `api/` FastAPI · SQLAlchemy async · auto docs at `/docs`
- `api/app/services/config_engine/` config resolution per the Indeed spec (shared with v2 Config Lab)
- `web/` Vite + React + TS + Tailwind

## How PR Finder scores

Crawl is hybrid: (1) your Sources repos, (2) a GitHub-wide hunt for open PRs
CodeRabbit has already reviewed (`commenter:coderabbitai[bot]`, one search per
use-case signature). When the bot's review exists, we parse it and score on
*evidence* — diagram/walkthrough/committable/etc. actually present (`scored_by:
review`, 85–98). Otherwise predictive heuristics (40 baseline ± signals), with
optional LLM refinement ≥60. Tune via `DISCOVERY_ENABLED` /
`DISCOVERY_PER_USE_CASE` env vars.

## v1 deviations from spec (deliberate, small)

- Background jobs use FastAPI BackgroundTasks instead of arq/Redis (one less service; swap in at M4).
- NL search is LLM-intent + keyword ranking; pgvector embeddings land in M2.
