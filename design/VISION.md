# CodeRabbit Demo Finder — Vision & Architecture Spec

**Status:** Draft for approval · **Owner:** Sindu · **Date:** 2026-08-25

## 1. What this is

An internal tool that finds, curates, and manufactures the perfect PR to demo any CodeRabbit capability. Three core loops:

1. **Find** — pull open PRs (GitHub API, GitLab later) from open source + your connected orgs (CodeRabbit org excluded), score them as demo candidates per use case, and format output for demos.
2. **Ask** — natural-language search ("show me a Terraform PR with a pipeline failure and a committable suggestion") that searches indexed repos and open source for a matching example.
3. **Manufacture** — when no solid example exists: recommend the best forkable repo, generate the exact change to make, the ideal `.coderabbit.yaml` (or custom `.ts` review instruction file), and open the PR so CodeRabbit produces the desired review style.

## 2. Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | **Python 3.12 + FastAPI** | Best GitHub/GitLab client + LLM ecosystem; async; typed with Pydantic |
| API docs | **FastAPI auto-OpenAPI** — Swagger UI at `/docs`, ReDoc at `/redoc` | Zero-maintenance, always in sync with code |
| DB | **Postgres 16 + SQLAlchemy 2 (async) + Alembic** | Relational fits repos/PRs/use-cases; `pgvector` extension for NL search embeddings |
| Frontend | **React 18 + Vite + TypeScript + Tailwind + shadcn/ui** | Fast dev loop; component library keeps the "make it standard later" path cheap |
| Background jobs | **arq** (Redis-backed, asyncio) | PR crawling/scoring runs out-of-band; simpler than Celery |
| Git providers | GitHub via `githubkit` (App or PAT), GitLab via `python-gitlab` (v1.1) | |
| LLM | Anthropic API for scoring, NL search intent parsing, change/config generation | |
| Deploy (v1) | `docker-compose up` — api, web, postgres, redis | Local-first; Cloud Run later |

Repo layout (monorepo at `coderabbit-demo/`):

```
coderabbit-demo/
├── api/          # FastAPI app
│   ├── app/
│   │   ├── routers/        # pr_finder, examples, forks, sources, config_lab (v2)
│   │   ├── services/       # github, gitlab, scoring, search, fork_engine, config_gen
│   │   ├── models/         # SQLAlchemy
│   │   ├── schemas/        # Pydantic
│   │   └── workers/        # arq tasks: crawl, score, index
│   └── alembic/
├── web/          # Vite + React
├── design/       # this doc + mockup
└── docker-compose.yml
```

## 3. Use-case taxonomy (first-class, seeded in DB)

Each use case has: `slug`, `name`, `category`, `detection_heuristics` (what makes a PR a good candidate), `required_config` (yaml keys that must be on), and `demo_script_notes`.

Seed list: Summarization/Walkthrough · Learnings (search query) · Tools · Code Review · Committable Suggestions · Sequence Diagrams · Request Changes (Approval) · Chat · Jira Integration (pre-merge check) · Assessment Against Linked Issues · Create Issues (GitHub/GitLab native) · Related PRs · Related Issues · Suggested Reviewers · Pipeline Failure · Docstrings · Automatic Unit Test Generation · MCP Client · Pre-Merge Checks · Code Guidelines / Index · Path Instructions & Filters · Web Search · Planning · Agentic Chat (performance issue) · Multi-repo Example · Atlas / Change Stack.

**Custom use cases:** anything not on the list is created via natural language — the LLM converts the description into a new use-case row (heuristics + required config), then the normal Find → Ask → Manufacture pipeline runs against it. GitHub + GitLab only for now.

## 4. Data model (Postgres)

```
source_org        id, provider(github|gitlab), org_name, connection_type(oss|personal|org),
                  included(bool)           -- you choose which repos to include; coderabbit org hard-excluded
repo              id, source_org_id, full_name, provider, default_branch, languages[],
                  has_coderabbit(bool), stars, forkable(bool), indexed_at
use_case          id, slug, name, category, detection_heuristics(jsonb),
                  required_config(jsonb), is_custom(bool), created_from_prompt(text)
pr_candidate      id, repo_id, pr_number, title, url, state, files_changed(jsonb),
                  diff_stats(jsonb), crawled_at
candidate_score   pr_candidate_id, use_case_id, score(0-100), rationale(text), scored_at
example           id, use_case_id, pr_candidate_id, status(candidate|approved|archived),
                  demo_notes, formatted_output(jsonb), embedding(vector)   -- pgvector for NL search
fork_suggestion   id, use_case_id, base_repo_id, rationale, suggested_changes(jsonb),
                  suggested_config(yaml text), config_kind(yaml|ts), status(draft|forked|pr_opened),
                  fork_url, pr_url
search_log        id, query, parsed_intent(jsonb), results(jsonb), created_at
```

## 5. API surface (FastAPI, auto-documented)

```
POST /sources/orgs                 connect org / choose included repos
GET  /use-cases                    list (seeded + custom)
POST /use-cases/from-prompt        NL → new use case
POST /crawl                        enqueue PR crawl for included repos
GET  /candidates?use_case=&min_score=   scored demo candidates
POST /search                       NL example search → ranked examples
POST /fork-suggestions             use_case → best forkable repo + changes + config
POST /fork-suggestions/{id}/execute     fork, branch, commit changes + config, open PR
GET  /examples/{id}/export         formatted output (markdown/JSON) for demo use
```

## 6. The three pipelines

**Find (crawl + score).** arq worker pulls open PRs from included repos → stores `pr_candidate` → LLM scores each PR against every use case's heuristics (e.g. Sequence Diagrams wants multi-file control-flow changes; Pipeline Failure wants a red CI check; Committable Suggestions wants small, fixable diffs) → top scores surface in the Finder UI with a "why" rationale and one-click formatted export.

**Ask (NL search).** Query → LLM parses intent (use case, language, file types, provider) → hybrid search: structured filters + pgvector similarity over indexed examples → if results are weak (`max score < threshold`), automatically pivots to Manufacture and says so.

**Manufacture (fork engine).** For a use case with no good example: rank forkable repos (language/file-type fit, activity, license, no CodeRabbit conflicts) → LLM generates (a) the file change that will trigger the desired review behavior, (b) the ideal `.coderabbit.yaml` — or a custom `.ts` instruction file when the use case needs custom review methods — with each key annotated for why it's set → you approve → tool forks into your environment, commits, opens the PR → CodeRabbit reviews it. Special inputs handled: `.sql` files, unusual config formats, customer-like repo shapes.

## 7. Config engine (v2 — designed now, built later)

Not in v1, but the architecture reserves for it, using the Indeed draft spec as the baseline. The fork engine's config generator and the future Config Lab share one module: `services/config_engine/`.

- **`resolver.py`** implements the spec exactly: `get_repo_config()` → `accumulate()` walk (first-writer-wins, repo → includes → central chain → org → workspace), `fill_gaps` vs `apply_overrides` as the two opposite primitives, schema defaults as final fill, global overrides as final overwrite, `inheritance: false` opt-out, `remote_config` as exclusive non-inheriting redirect, list merge by identity (path/name/id/key/label, child first).
- **`tree.py`** builds/validates the config_node tree (cycle detection, nested group centrals threaded nearest-first, UI settings as ordinary nodes) — cached, rebuilt on config change.
- **v1 consumes it minimally:** the fork engine uses schema defaults + generated yaml so suggested configs are always resolution-valid.
- **v2 Config Lab UI:** paste/pick repo + central + org + workspace configs → resolved output with per-key "won by" trace (exactly the worked example in the spec, live). The mockup shows this as a teaser tab.

## 8. v1 scope cut

**In:** GitHub only · seeded use cases + NL custom use cases · crawl/score/finder UI · NL search over indexed examples · fork suggestion generation + one-click fork/PR · repo include/exclude settings · formatted export.
**Out (v2):** GitLab crawling · Config Lab · multi-repo/Atlas orchestration demos · auth/multi-user · Jira/MCP live integrations (v1 documents the config, doesn't wire them).

## 9. Milestones

1. **M0 (this doc + mockup)** — approve vision.
2. **M1 (~week)** — scaffold, DB, GitHub crawl, use-case seed, Finder UI with scores.
3. **M2** — NL search + custom use cases.
4. **M3** — fork engine end-to-end (suggestion → fork → PR).
5. **M4 (feedback-driven)** — GitLab, Config Lab, hardening ("make it standard").
