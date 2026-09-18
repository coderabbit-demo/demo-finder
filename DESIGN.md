# CodeRabbit Demo Finder — Engineering Design

**Status:** living document — edit freely, log changes in §12
**Owner:** Sindu · **Last updated:** 2026-08-26
**Companions:** `design/VISION.md` (original approved vision, frozen) · `README.md` (run instructions)

## 1. Purpose

Find, curate, and manufacture the perfect PR to demo any CodeRabbit capability. Three loops: **Find** (crawl + GitHub-wide discovery of bot-reviewed PRs, scored per use case), **Ask** (natural-language search over indexed examples), **Manufacture** (fork the best base repo, generate the change + config, open a PR that triggers the desired review).

**Non-goals (v1):** GitLab crawling, multi-user auth, live Jira/MCP integrations (we generate the config, we don't wire the integration), the interactive Config Lab UI.

## 2. System overview

```
web (React/Vite/TS, :3001)
  └─ /api proxy ──► api (FastAPI, :8000)
                      ├─ routers/    sources · use_cases · candidates · search · forks · examples
                      ├─ services/   github · scoring · discovery · search · fork_engine · llm
                      │              └─ config_engine/  resolver (Indeed spec) · schema_defaults
                      └─ db          SQLite (dev) / Postgres (compose), SQLAlchemy 2 async
external: GitHub REST + Search API · Anthropic API (optional)
```

State lives in one DB. Crawls run as FastAPI BackgroundTasks (single-process; arq/Redis is the planned upgrade if crawls need retry/parallelism). Frontend is hash-routed (`#/finder?uc=…&min=…`) so every view is a shareable deep link.

## 3. Data model

| Table | Purpose | Notable columns |
|---|---|---|
| `source_org` | A connected origin of repos | `connection_type: oss\|personal\|org\|discovered\|fixture`, `included` |
| `repo` | Crawlable repo | `full_name` unique, `included`, `forkable`, `has_coderabbit`, `languages` |
| `use_case` | Demo capability taxonomy (30 seeded + custom) | `detection_heuristics` (jsonb), `required_config` (dotted keys), `is_custom`, `created_from_prompt` |
| `pr_candidate` | A crawled/discovered open PR | `files_changed`, `diff_stats`, **`evidence_urls`** (evidence key → bot-comment anchor URL) |
| `candidate_score` | (candidate × use case) score | `score 0-100`, `rationale`, `scored_by: review\|llm\|heuristic` |
| `example` | Flagged keeper (★ in UI) | `status: approved`, survives re-crawls |
| `fork_suggestion` | Manufacture pipeline state | `suggested_changes`, `suggested_config`, `config_kind: yaml\|ts`, `status: draft\|pr_opened\|failed` |
| `search_log` | NL query audit trail | `parsed_intent`, `results` |

Migrations: `Base.metadata.create_all` + ad-hoc `ALTER TABLE` in `db.init_db()` for added columns. **Debt:** move to Alembic before schema churn gets real.

### Data lifecycle rules
- Re-crawl wipes a repo's candidates + scores **except** candidates referenced by an approved `example` (flags are permanent until unflagged).
- Startup heals orphaned scores (bulk deletes bypass ORM cascades) and, when `DEV_MODE=false`, purges all `fixture` data.
- `coderabbitai` org is hard-excluded everywhere (`settings.excluded_orgs`).

## 4. Scoring pipeline (the core)

**One scale, non-overlapping bands — proof always outranks prediction:**

| Range | Meaning | Producer |
|---|---|---|
| 99–100 | reserved (verified + human-flagged, future) | — |
| 85–98 | **verified** — capability provably present in CodeRabbit's actual review | `scored_by: review` |
| 70–84 | strong candidate (predicted) | `heuristic` / `llm` |
| 50–69 | usable (predicted) | `heuristic` / `llm` |
| < 50 | weak | `heuristic` |

1. **Evidence-based (85–98).** If `coderabbitai[bot]` commented, regex-match `EVIDENCE_PATTERNS` against the comments; a hit on the use case's signature keys is proof. 85 base + 3·|evidence| breadth bonus, cap 98. Deterministic — no LLM in the verification path.
2. **Predicted (≤84, hard cap).** Weighted scoring model (`scoring.WEIGHTS`, sums to 1): `capability_fit` 0.55 (mean of the use case's applicable detectors, each normalized 0–1) · `size_fit` 0.20 (diff inside the demo-able window) · `repo_quality` 0.15 (log-scaled stars) · `freshness` 0.10 (neutral 0.5 until PR `updated_at` is captured). Missing signals score neutral, never punitive. Rationale lists each criterion's value.
3. **LLM refine** (optional, prior ≥ 60): re-scores within the predicted band, also capped at 84.

**Accuracy sources (do not define features from memory):** use-case `definition` is quoted or closely paraphrased from the current CodeRabbit documentation and `doc_url` links to the supporting page; config keys are verified against the live schema `https://storage.googleapis.com/coderabbit_public_assets/schema.v2.json`. The catalog includes documented Change Stack, Multi-Repo Analysis, Security Blast Radius, Security Architecture Review, Attack Surface, and AI Deep Scan behavior. Seeds upsert on every boot so definition fixes propagate to existing DBs.

### Deep-link anchors
`evidence_anchors()` maps each evidence key to the `html_url` of the first bot comment proving it (`#issuecomment-…` / `#discussion_r…`). Stored on `pr_candidate.evidence_urls`; `anchor_for_use_case()` picks the right anchor per use case. Exposed as `pr.anchor_url` in `/candidates` and in exports; UI shows 🎯. Anchors are backfilled three ways during crawl: re-discovered PRs, flagged keepers hit in layer 1, and a sweep of ≤40 anchor-less candidates per crawl (layer 3).

## 5. Crawl = three layers (`routers/candidates.py::_crawl_and_score`)

1. **Sources crawl** — for each included repo in non-discovered/non-fixture orgs: pull ≤30 open PRs (files, CI), evidence-score if the bot reviewed, else heuristic/LLM.
2. **Discovery** — GitHub-wide Search API hunt, one query per use-case signature: `commenter:coderabbitai[bot] is:pr is:open "<phrase>" in:comments`, ≤`DISCOVERY_PER_USE_CASE` (5) hits each, 2s pacing (search limit is 30/min). Discovered repos auto-register under a `discovered` org, toggleable in Sources. Gated by `DISCOVERY_ENABLED` + token present.
3. **Anchor backfill sweep** — heal candidates that predate anchor capture.

Failure posture: every per-repo/per-PR GitHub call is try/except-continue; a bad repo never kills the crawl. **Debt:** no crawl status surfaced to the UI (fire-and-forget 202).

## 6. NL search (`services/search.py`)

Query → deterministic ranking against each use case's documented name, definition, demo guidance, detector terms, and config keys → language/file filtering → candidate ranking by evidence quality (62%), capability relevance (23%), query context (10%), and demo size (5%). Clear queries do not call the LLM; only ambiguous queries request a constrained second opinion using known slugs. The response explains each recommended capability, shows setup effort and verified-example counts, then ranks the top 10 PRs. Verified CodeRabbit review evidence receives a small tie-break bonus. If the best result is below 70, the UI offers the Forge hand-off with intent pre-filled. Every query is logged to `search_log`. **Planned (M2):** embeddings over approved examples as an additional retrieval signal, not a replacement for evidence ranking.

## 7. Manufacture / fork engine (`services/fork_engine.py`)

1. **Rank forkable bases:** language fit vs use-case `file_exts`, no existing `.coderabbit.yaml` (+15 / −20 if present), realistic activity, `forkable && included`. Alternatives returned for transparency.
2. **Generate:** LLM produces minimal file change(s) + config (`config_yaml` or `config_ts` for custom review methods). Fallback without LLM: deterministic seed file + config expanded from `use_case.required_config` (dotted keys → nested yaml), shape-checked against `config_engine.schema_defaults` so it's resolution-valid by construction.
3. **Execute** (`services/github.py::fork_and_open_pr`): fork to token owner → branch → commit files (+ `.coderabbit.yaml` or `.coderabbit/review.ts`) → PR **against the fork's own default branch** so CodeRabbit reviews inside your environment. Requires CodeRabbit installed on the fork's account.

## 8. Config engine (`services/config_engine/`) — the Indeed spec

`resolver.py` implements the draft spec exactly and is fully unit-tested (worked example + trace + opt-out + remote_config + includes + list merge):

- `get_repo_config()` = `accumulate()` walk (first-writer-wins: repo → includes last-listed-wins → central chain → org → workspace) bracketed by `fill_gaps(schema_defaults)` (final fill) and `apply_overrides(global_overrides)` (final overwrite — enforced lists *replace*).
- `inheritance: false` stops the walk at that node; `remote_config` is an exclusive, non-inheriting redirect (`parent=null` on remote/include nodes).
- `merge_lists` dedups by identity (`path|name|id|key|label`), child items first.
- `resolve_with_trace()` returns per-key "won by" — this powers the v2 Config Lab UI.

v1 consumer: fork engine (schema-default validation). v2: interactive Config Lab tab (teaser ships now).

## 9. API surface

FastAPI auto-docs at `/docs`. Key routes: `GET/POST/PATCH/DELETE /sources/*` (auto-discovery of org repos when the repo list is omitted) · `GET /use-cases`, `POST /use-cases/from-prompt` · `POST /crawl` (202) · `GET /candidates?use_case=&min_score=` · `GET /candidates/{id}/export?use_case=` · `POST /search` · `POST /fork-suggestions`, `POST /fork-suggestions/{id}/execute` · `POST /examples` (flag toggle), `GET /examples` · `GET /health` (dev_mode/github/llm capability flags shown in the sidebar).

## 10. Frontend conventions

Hash routing via `App.tsx::nav()`; pages sync their state to the URL with `history.replaceState` (shareable without history spam). Data layer is one typed fetch client (`lib/api.ts`) — keep response-shape changes mirrored there. Styling: Tailwind v4 theme tokens in `index.css` (`--color-accent` etc.); no component library. Errors surface in red banners, never silently.

## 11. Config & environments

| Env var | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./demo.db` | Postgres via compose |
| `GITHUB_TOKEN` | — | crawl/discovery/fork; classic PAT `repo` scope, SSO-authorized |
| `ANTHROPIC_API_KEY` | — | LLM scoring/intent/generation (graceful heuristics without) |
| `DEV_MODE` | `false` | seed fixtures; **off purges them at startup** |
| `DISCOVERY_ENABLED` / `DISCOVERY_PER_USE_CASE` | `true` / `5` | GitHub-wide hunt tuning |

Tests: `cd api && python -m pytest` (resolver spec compliance + evidence extraction/anchors). Frontend: `npx tsc -b` gates the build.

## 12. Known debt & roadmap

Debt: Alembic migrations · arq for background jobs (crawl state is in-memory, single-process) · GitHub App auth instead of PAT · rate-limit budgeting for large Sources lists · PR `updated_at` capture (freshness criterion is neutral until then).

Roadmap: **M2** pgvector NL search, GitLab discovery · **M3** fork-engine polish (multi-file changes, `.sql`/config-shaped seeds, customer-shape matching) · **M4** Config Lab interactive, hardening ("make it standard": authz, arq, GitHub App).

### Changelog
- 2026-09-18 — docs-backed capability search; deterministic intent parsing for clear queries; explainable use-case recommendations; language filtering; verified-evidence and demo-efficiency ranking; current Change Stack and Security taxonomy.
- 2026-08-26 (b) — docs-accurate taxonomy (definitions quoted from coderabbit-docs, keys verified vs live schema, `[Not documented]` flags); weighted scoring rubric with banded scale + predicted cap 84; GraphQL PR snapshot (1 call vs 4, fixes ci_status); crawl progress (`/crawl/status` + live UI banner); `/docs-sync` live-schema key validation; GitHub Actions CI; rubric unit tests.
- 2026-08-26 — evidence anchors + backfill; fixture purge on `DEV_MODE=false`; hash deep links; flags (`example`) + library deep links; hybrid discovery + evidence scoring; sources auto-discovery + delete; initial v1.
