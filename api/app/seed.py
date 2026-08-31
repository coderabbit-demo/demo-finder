"""Seed data: the use-case taxonomy and (in DEV_MODE) sample repos/PRs/scores."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import CandidateScore, PrCandidate, Repo, SourceOrg, UseCase

# detection_heuristics keys the heuristic scorer understands:
#   keywords: title/body terms   file_exts: preferred extensions
#   min_files / max_files        ci_status: green|red|any
#   needs_linked_issue / needs_multi_service / prefers_new_module: bools
#
# ACCURACY SOURCES — do not edit definitions/config keys from memory:
#   definitions: coderabbit-docs repo (docs.coderabbit.ai source), quoted or minimally trimmed
#   config keys: live schema https://storage.googleapis.com/coderabbit_public_assets/schema.v2.json
#   features the docs DON'T define are marked "[Not documented: ...]" — keep that honesty.
DOCS = "https://docs.coderabbit.ai"

USE_CASES: list[dict] = [
    dict(slug="summarization", name="Summarization / Walkthrough", category="review",
         definition="Generate a high level summary of the changes in the PR/MR description. CodeRabbit posts a comment titled 'Walkthrough' containing analysis and commentary about the content of the pull request.",
         doc_url=f"{DOCS}/reference/configuration",
         detection_heuristics={"min_files": 4, "max_files": 25, "keywords": ["refactor", "feature", "add", "implement"]},
         required_config={"reviews.high_level_summary": True, "reviews.changed_files_summary": True,
                          "reviews.collapse_walkthrough": False},
         demo_script_notes="Open the walkthrough comment; scroll the file-by-file table."),
    dict(slug="learnings", name="Learnings (search query)", category="knowledge",
         definition="As your team works with CodeRabbit, it learns your team's code-review preferences based on chat interactions, and adds these preferences to an internal database associated with your Git platform organization.",
         doc_url=f"{DOCS}/guides/learnings",
         detection_heuristics={"keywords": ["convention", "pattern", "style"], "min_files": 1},
         required_config={"knowledge_base.learnings.scope": "auto"},
         demo_script_notes="Query accumulated learnings live in chat."),
    dict(slug="tools", name="Tools (linters / SAST)", category="review",
         definition="CodeRabbit supports various linters and security analysis tools to improve the code review process. Tool output enhances CodeRabbit's feedback, making 1-click fixes possible; all runs happen in a secure sandboxed execution environment.",
         doc_url=f"{DOCS}/tools",
         detection_heuristics={"keywords": ["lint", "security", "fix"], "file_exts": [".py", ".ts", ".go", ".tf"]},
         required_config={"reviews.tools.ruff.enabled": True, "reviews.tools.semgrep.enabled": True,
                          "reviews.profile": "assertive"},
         demo_script_notes="Show a tool finding surfaced inline. Profile controls how much tool output surfaces."),
    dict(slug="code-review", name="Code Review (core)", category="review",
         definition="The central feature of CodeRabbit: proactively reviews new pull requests as PR comments that include summaries, analyses, and initial critiques of the proposed changes. Profile: 'chill' (default) vs 'assertive' (deeper, more verbose, can get nitpicky).",
         doc_url=f"{DOCS}/guides/code-review-overview",
         detection_heuristics={"min_files": 2, "max_files": 15, "keywords": ["fix", "bug", "handle"]},
         required_config={"reviews.profile": "chill"},
         demo_script_notes="Classic inline comments on a realistic diff."),
    dict(slug="committable-suggestions", name="Committable Suggestions", category="review",
         definition="Review comments can post committable suggestions that can be committed within the pull request with a single click. [Not documented as a feature page; no yaml key — built-in review behavior.]",
         doc_url=f"{DOCS}/changelog",
         detection_heuristics={"max_files": 6, "keywords": ["fix", "bug", "null", "race", "off-by-one", "leak"]},
         required_config={},
         demo_script_notes="Small fixable defect; click 'commit suggestion' live."),
    dict(slug="sequence-diagrams", name="Sequence Diagrams", category="review",
         definition="Generate sequence diagrams in the walkthrough — a visual diagram of object interactions. On-demand via '@coderabbitai generate sequence diagram'.",
         doc_url=f"{DOCS}/reference/configuration",
         detection_heuristics={"min_files": 3, "needs_multi_service": True, "keywords": ["flow", "webhook", "queue", "pipeline", "async", "retry", "handler"]},
         required_config={"reviews.sequence_diagrams": True},
         demo_script_notes="Multi-actor control flow renders a rich mermaid diagram."),
    dict(slug="request-changes", name="Request Changes (Approval)", category="workflow",
         definition="If enabled, CodeRabbit marks a pull request as approved once all comments that CodeRabbit made have been resolved — so CodeRabbit's approval can count towards required approvals before merge.",
         doc_url=f"{DOCS}/reference/configuration",
         detection_heuristics={"keywords": ["breaking", "migration", "drop", "delete"], "ci_status": "any"},
         required_config={"reviews.request_changes_workflow": True},
         demo_script_notes="Show resolve-all-comments → approval flip."),
    dict(slug="chat", name="Chat", category="chat",
         definition="CodeRabbit Chat is a pull-request-specific assistant: interact directly in PR review comments and PR comments to ask questions, have CodeRabbit rewrite code, or generate new code.",
         doc_url=f"{DOCS}/guides/agent_chat",
         detection_heuristics={"min_files": 2, "keywords": []},
         required_config={"chat.auto_reply": True},
         demo_script_notes="Ask CodeRabbit a question on any review thread."),
    dict(slug="jira-integration", name="Jira Integration", category="integrations",
         definition="CodeRabbit integrates with issue tracking systems to provide context from linked and related issues while reviewing code. 'auto' disables the integration for public repositories.",
         doc_url=f"{DOCS}/integrations/issue-integrations",
         detection_heuristics={"needs_linked_issue": True, "keywords": ["JIRA", "PROJ-", "ticket"]},
         required_config={"knowledge_base.jira.usage": "enabled",
                          "reviews.pre_merge_checks.issue_assessment.mode": "warning"},
         demo_script_notes="Linked Jira ticket feeds review context; pre-merge issue assessment validates against it."),
    dict(slug="linked-issues", name="Assessment Against Linked Issues", category="workflow",
         definition="Reviews include assessments of how well a proposed code change addresses any issues the pull request refers to (by number in the title, description, or GitHub's Development field).",
         doc_url=f"{DOCS}/guides/linked-issues",
         detection_heuristics={"needs_linked_issue": True, "keywords": ["closes", "fixes", "resolves"]},
         required_config={"reviews.assess_linked_issues": True},
         demo_script_notes="Scope mismatch between PR body and linked issue gets flagged."),
    dict(slug="create-issues", name="Create Issues (Git-provider native)", category="workflow",
         definition="CodeRabbit provides seamless issue creation across GitHub, GitLab, Jira, and Linear — create issues directly from pull request discussions or through the agentic chat interface. [GitHub/GitLab need no setup; no direct yaml key.]",
         doc_url=f"{DOCS}/guides/issue-creation",
         detection_heuristics={"keywords": ["todo", "followup", "tech debt"]},
         required_config={},
         demo_script_notes="Turn a review finding into a GitHub/GitLab issue from the comment."),
    dict(slug="related-prs", name="Related PRs", category="context",
         definition="Include possibly related pull requests in the walkthrough. Corpus scope set by knowledge_base.pull_requests.scope (local/global/auto).",
         doc_url=f"{DOCS}/reference/configuration",
         detection_heuristics={"keywords": ["also", "similar", "follow-up"]},
         required_config={"reviews.related_prs": True, "knowledge_base.pull_requests.scope": "auto"},
         demo_script_notes="Repo with overlapping in-flight work; show the related-PRs panel."),
    dict(slug="related-issues", name="Related Issues", category="context",
         definition="Include possibly related issues in the walkthrough. Corpus scope set by knowledge_base.issues.scope (local/global/auto).",
         doc_url=f"{DOCS}/reference/configuration",
         detection_heuristics={"needs_linked_issue": True},
         required_config={"reviews.related_issues": True, "knowledge_base.issues.scope": "auto"},
         demo_script_notes="Related-issues panel on the walkthrough."),
    dict(slug="suggested-reviewers", name="Suggested Reviewers", category="workflow",
         definition="Suggest reviewers based on the changes in the pull request in the walkthrough. auto_assign_reviewers additionally assigns them automatically.",
         doc_url=f"{DOCS}/reference/configuration",
         detection_heuristics={"min_files": 2, "keywords": []},
         required_config={"reviews.suggested_reviewers": True},
         demo_script_notes="Repo with commit-history ownership signal."),
    dict(slug="pipeline-failure", name="Pipeline Failure Remediation", category="ci",
         definition="Automatically detects and fixes build failures across CI/CD pipelines, analyzing failures in real-time with inline comments and actionable suggestions (GitHub Actions, GitLab CI/CD, CircleCI, Azure DevOps). [No dedicated yaml key; github-checks tool reads CI results.]",
         doc_url=f"{DOCS}/tools/pipeline-remediation",
         detection_heuristics={"ci_status": "red", "keywords": ["ci", "test", "build"]},
         required_config={"reviews.tools.github-checks.enabled": True},
         demo_script_notes="Red CI check; CodeRabbit diagnoses the failure in review."),
    dict(slug="docstrings", name="Docstrings (Finishing Touches)", category="generation",
         definition="CodeRabbit can generate inline documentation for functions added in a pull request — via '@coderabbitai generate docstrings' or the Generate Docstrings checkbox under Finishing Touches in the walkthrough; it opens a PR against your PR branch.",
         doc_url=f"{DOCS}/finishing-touches/docstrings",
         detection_heuristics={"file_exts": [".py", ".ts"], "prefers_new_module": True, "keywords": ["add", "new", "api"]},
         required_config={"reviews.finishing_touches.docstrings.enabled": True,
                          "code_generation.docstrings.language": "en-US"},
         demo_script_notes="Trigger docstring generation on undocumented public functions."),
    dict(slug="unit-tests", name="Unit Test Generation (Finishing Touches)", category="generation",
         definition="CodeRabbit can generate unit tests for code added in a pull request. Beta, Pro plan; GitHub-only forge support.",
         doc_url=f"{DOCS}/finishing-touches/unit-test-generation",
         detection_heuristics={"prefers_new_module": True, "file_exts": [".py", ".ts", ".go"], "keywords": ["add", "implement", "util", "parser"]},
         required_config={"reviews.finishing_touches.unit_tests.enabled": True},
         demo_script_notes="New pure-logic module with no test file; generate tests."),
    dict(slug="mcp-client", name="MCP Client", category="integrations",
         definition="Connect CodeRabbit to external tools and data sources through Model Context Protocol: CodeRabbit serves as the client, gaining richer context for code reviews, suggestion validation, and PR chat. Pro, Early Access; server setup is via the app UI (Integrations → MCP Server).",
         doc_url=f"{DOCS}/context-enrichment/mcp-server-integrations",
         detection_heuristics={"needs_linked_issue": True, "keywords": ["issue", "linear", "notion"]},
         required_config={"knowledge_base.mcp.usage": "enabled"},
         demo_script_notes="Review enriched by an MCP server (e.g. Linear) connection."),
    dict(slug="pre-merge-checks", name="Pre-Merge Checks", category="workflow",
         definition="Checks that gate merging: docstring coverage threshold, title requirements, description quality, linked-issue assessment, plus custom checks with deterministic pass/fail instructions. Modes: off/warning/error — 'error' requires resolution before merging. [Schema-defined; no prose docs page yet.]",
         doc_url=f"{DOCS}/reference/configuration",
         detection_heuristics={"keywords": ["title", "coverage", "checklist"]},
         required_config={"reviews.pre_merge_checks.title.mode": "warning",
                          "reviews.pre_merge_checks.custom_checks": [
                              {"mode": "warning", "name": "Title format",
                               "instructions": "Title follows conventional commits."}]},
         demo_script_notes="Custom check gates the merge; show warning vs error modes."),
    dict(slug="code-guidelines", name="Code Guidelines", category="knowledge",
         definition="CodeRabbit reads code guideline files that set standards about your team's coding practices in natural language, and applies them to all reviews. Auto-detects files used by other AI assistants (.cursorrules, CLAUDE.md, copilot-instructions.md, etc.).",
         doc_url=f"{DOCS}/integrations/knowledge-base",
         detection_heuristics={"keywords": ["style", "contributing", "guideline"]},
         required_config={"knowledge_base.code_guidelines.enabled": True,
                          "knowledge_base.code_guidelines.filePatterns": ["**/STYLEGUIDE.md"]},
         demo_script_notes="Repo with guideline files; review cites them. NOTE: filePatterns is camelCase in the schema."),
    dict(slug="path-instructions", name="Path Instructions & Filters", category="config",
         definition="Path instructions: natural-language review instructions per file path (extended glob). Path filters: restrict which parts of the repo CodeRabbit uses for context — '!' prefixes exclude; any include path makes the list allowlist-only.",
         doc_url=f"{DOCS}/guides/review-instructions",
         detection_heuristics={"min_files": 5, "keywords": ["monorepo", "packages", "apps"]},
         required_config={"reviews.path_instructions": [
                              {"path": "**/*.sql", "instructions": "Flag missing indexes and non-concurrent migrations."}],
                          "reviews.path_filters": ["!**/dist/**"]},
         demo_script_notes="Monorepo with per-path rules; show a .sql-specific comment."),
    dict(slug="web-search", name="Web Search", category="context",
         definition="CodeRabbit integrates real-time web search, fetching up-to-date information to support reviews and chat responses; replies indicate when it searched the web.",
         doc_url=f"{DOCS}/reference/configuration",
         detection_heuristics={"keywords": ["upgrade", "bump", "cve", "deprecat"]},
         required_config={"knowledge_base.web_search.enabled": True},
         demo_script_notes="Dependency with a recent CVE; review cites the advisory."),
    dict(slug="planning", name="Planning (@coderabbitai plan)", category="agentic",
         definition="Request CodeRabbit to generate improvements to a branch it is reviewing: 'plan' is shorthand for 'implement the changes you suggested in your code review' — CodeRabbit creates a new branch and PR linked from the original. GitHub-only; no yaml key.",
         doc_url=f"{DOCS}/guides/generate-improvements",
         detection_heuristics={"needs_linked_issue": True, "keywords": ["plan", "implement", "feature"]},
         required_config={},
         demo_script_notes="Comment '@coderabbitai plan' → branch → linked PR."),
    dict(slug="agentic-chat", name="Agentic Chat (performance issue)", category="agentic",
         definition="For complex coding challenges, Agentic Chat supports multi-step agentic flows with detailed planning and execution; CodeRabbit can issue a PR for the changes, commit to the existing branch, or produce copyable snippets. Invocation-only; GitHub-only; no yaml key.",
         doc_url=f"{DOCS}/guides/agent_chat",
         detection_heuristics={"keywords": ["performance", "slow", "n+1", "optimize", "cache"]},
         required_config={},
         demo_script_notes="Perf-issue PR; agentic chat investigates and proposes a fix."),
    dict(slug="multi-repo", name="Multi-repo / Org-wide Context", category="context",
         definition="Cross-repo context via knowledge-base scopes: 'global' uses the organization's learnings/issues/PRs across all repositories; 'auto' is repo-scoped for public repos, org-scoped for private. [No dedicated docs page — this is the scope mechanism.]",
         doc_url=f"{DOCS}/guides/learnings",
         detection_heuristics={"keywords": ["proto", "contract", "client", "sdk"]},
         required_config={"knowledge_base.learnings.scope": "global",
                          "knowledge_base.pull_requests.scope": "global",
                          "knowledge_base.issues.scope": "global"},
         demo_script_notes="Learning taught in repo A cited in repo B's review."),
    dict(slug="atlas-change-stack", name="Atlas / Change Stack", category="agentic",
         definition="[Not documented publicly. 'Stacked PR' appears only in the changelog as an output of agentic planning: 'CodeRabbit will emit a stacked PR, commit or copyable snippet to your PR or issue.' No feature page, no config key — treat as internal/roadmap terminology.]",
         doc_url=f"{DOCS}/changelog",
         detection_heuristics={"min_files": 6, "keywords": ["stack", "part 1", "part 2", "series"]},
         required_config={},
         demo_script_notes="Stacked changes reviewed as one narrative — demo via agentic planning output."),
]

DEV_FIXTURES = {
    "orgs": [
        dict(org_name="oss-curated", connection_type="fixture", repos=[
            dict(full_name="stripe/stripe-python", languages=["python"], stars=1800, prs=[
                dict(pr_number=4821, title="Refactor payment webhook retry flow",
                     files_changed=["stripe/webhook.py", "stripe/queue.py", "stripe/retry_handler.py", "stripe/db.py", "tests/test_webhook.py", "stripe/validator.py", "stripe/events.py"],
                     diff_stats={"additions": 412, "deletions": 188, "files": 7, "ci_status": "green"}),
                dict(pr_number=4830, title="Fix race condition in idempotency-key cache",
                     files_changed=["stripe/cache.py", "tests/test_cache.py"],
                     diff_stats={"additions": 58, "deletions": 12, "files": 2, "ci_status": "green"}),
            ]),
            dict(full_name="gruntwork-io/terragrunt", languages=["go", "terraform"], stars=8000, prs=[
                dict(pr_number=2891, title="Fix S3 bucket ACL security misconfig in remote state",
                     files_changed=["remote/remote_state_s3.go", "modules/state/main.tf"],
                     diff_stats={"additions": 44, "deletions": 9, "files": 2, "ci_status": "green"}),
            ]),
            dict(full_name="fastapi/full-stack-fastapi-template", languages=["python", "typescript"], stars=25000, prs=[
                dict(pr_number=1107, title="Add async batch processor for item imports",
                     files_changed=["backend/app/workers/batch.py", "backend/app/api/routes/items.py", "backend/app/queue.py", "frontend/src/api/items.ts"],
                     diff_stats={"additions": 230, "deletions": 41, "files": 4, "ci_status": "red"}),
            ]),
        ]),
        dict(org_name="sindu", connection_type="fixture", repos=[
            dict(full_name="sindu/rabbits-playground", languages=["go"], stars=3, prs=[
                dict(pr_number=233, title="Fix race in session cache, closes #12",
                     files_changed=["cache/session.go", "cache/session_test.go"],
                     diff_stats={"additions": 58, "deletions": 12, "files": 2, "ci_status": "green"}),
            ]),
            dict(full_name="sindu/aws-infra", languages=["terraform"], stars=1, prs=[
                dict(pr_number=47, title="Tighten security-group ingress, fixes PROJ-482",
                     files_changed=["modules/network/sg.tf"],
                     diff_stats={"additions": 12, "deletions": 6, "files": 1, "ci_status": "green"}),
            ]),
        ]),
    ]
}


async def seed_use_cases(session: AsyncSession) -> None:
    """Upsert: new slugs are inserted; existing non-custom rows get their
    docs-sourced fields refreshed every boot so accuracy fixes propagate."""
    existing = {u.slug: u for u in (await session.execute(select(UseCase))).scalars().all()}
    for uc in USE_CASES:
        row = existing.get(uc["slug"])
        if row is None:
            session.add(UseCase(**uc))
        elif not row.is_custom:
            for field in ("name", "category", "definition", "doc_url",
                          "required_config", "detection_heuristics", "demo_script_notes"):
                setattr(row, field, uc[field])
    await session.commit()


async def seed_dev_fixtures(session: AsyncSession) -> None:
    from .services.scoring import score_candidate  # late import to avoid cycle

    if (await session.execute(select(Repo.id))).first():
        return  # already seeded
    for org_data in DEV_FIXTURES["orgs"]:
        org = SourceOrg(org_name=org_data["org_name"], connection_type=org_data["connection_type"])
        session.add(org)
        await session.flush()
        for repo_data in org_data["repos"]:
            repo = Repo(source_org_id=org.id, full_name=repo_data["full_name"],
                        languages=repo_data["languages"], stars=repo_data["stars"])
            session.add(repo)
            await session.flush()
            for pr in repo_data["prs"]:
                cand = PrCandidate(repo_id=repo.id, pr_number=pr["pr_number"], title=pr["title"],
                                   url=f"https://github.com/{repo.full_name}/pull/{pr['pr_number']}",
                                   files_changed=pr["files_changed"], diff_stats=pr["diff_stats"])
                session.add(cand)
    await session.commit()

    # score every fixture candidate against every use case (heuristics only)
    use_cases = (await session.execute(select(UseCase))).scalars().all()
    candidates = (await session.execute(select(PrCandidate))).scalars().all()
    for cand in candidates:
        for uc in use_cases:
            score, rationale = score_candidate(cand, uc)
            if score > 0:
                session.add(CandidateScore(pr_candidate_id=cand.id, use_case_id=uc.id,
                                           score=score, rationale=rationale, scored_by="heuristic"))
    await session.commit()
