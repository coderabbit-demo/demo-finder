import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, CandidateScore, PrCandidate, Repo, SourceOrg, UseCase
from app.services import search


def use_case(slug: str, name: str, definition: str, category: str = "review",
             keywords: list[str] | None = None) -> UseCase:
    return UseCase(
        slug=slug,
        name=name,
        definition=definition,
        category=category,
        detection_heuristics={"keywords": keywords or []},
        required_config={},
        demo_script_notes="",
        doc_url=f"https://docs.coderabbit.ai/{slug}",
    )


USE_CASES = [
    use_case("security-blast-radius", "Security Blast Radius",
             "Map dependencies, downstream consumers, tests, and security paths.",
             "security", ["shared", "dependency", "consumer", "auth"]),
    use_case("security-deep-scan", "AI Deep Scan",
             "Scan committed code for exploitable vulnerabilities and exposed secrets.",
             "security", ["vulnerability", "secret", "scan"]),
    use_case("mcp-client", "MCP Client",
             "Use external documentation and project context during reviews.",
             "integrations", ["linear", "notion", "confluence"]),
    use_case("committable-suggestions", "Committable Suggestions",
             "Apply a suggested fix directly from a review comment.",
             keywords=["fix", "bug"]),
]


def test_docs_ranker_finds_blast_radius_from_product_language():
    ranked = search.rank_use_cases(
        "show the blast radius of a shared auth helper and downstream consumers", USE_CASES)

    assert ranked[0]["slug"] == "security-blast-radius"
    assert ranked[0]["score"] >= 60
    assert any("downstream" in reason for reason in ranked[0]["reasons"])


def test_docs_ranker_maps_external_context_to_mcp():
    ranked = search.rank_use_cases(
        "use Notion and Linear context while reviewing", USE_CASES)

    assert ranked[0]["slug"] == "mcp-client"
    assert ranked[0]["score"] >= 70


def test_clear_docs_match_skips_llm(monkeypatch):
    async def fail_if_called(**_kwargs):
        raise AssertionError("clear docs matches should not call the LLM")

    monkeypatch.setattr(search.llm, "complete_json", fail_if_called)
    intent = asyncio.run(search.parse_intent(
        "security blast radius for downstream consumers", USE_CASES))

    assert intent["parser"] == "docs"
    assert intent["use_case_slugs"][0] == "security-blast-radius"


def test_language_intent_expands_extensions():
    languages, extensions = search._language_intent("a Python and TypeScript security review")

    assert languages == ["python", "typescript"]
    assert {".py", ".ts", ".tsx"} <= set(extensions)


def test_small_candidate_is_more_demo_efficient():
    small = PrCandidate(repo_id=1, pr_number=1, title="small", url="u",
                        files_changed=["a.py", "b.py"],
                        diff_stats={"files": 2, "additions": 40, "deletions": 5})
    large = PrCandidate(repo_id=1, pr_number=2, title="large", url="u",
                        files_changed=[f"{index}.py" for index in range(30)],
                        diff_stats={"files": 30, "additions": 1500, "deletions": 500})

    small_score, small_label = search._candidate_efficiency(small)
    large_score, large_label = search._candidate_efficiency(large)

    assert small_score > large_score
    assert small_label == "quick"
    assert large_label == "large"


def test_search_returns_docs_recommendation_and_ranked_candidate(monkeypatch):
    async def fail_if_called(**_kwargs):
        raise AssertionError("clear docs matches should not call the LLM")

    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            org = SourceOrg(org_name="demo")
            session.add(org)
            await session.flush()
            repo = Repo(source_org_id=org.id, full_name="demo/service", languages=["python"])
            use_case_row = USE_CASES[0]
            session.add_all([repo, use_case_row])
            await session.flush()
            candidate = PrCandidate(
                repo_id=repo.id,
                pr_number=42,
                title="Route shared authorization through one helper",
                url="https://example.test/pull/42",
                files_changed=["api/auth.py", "api/routes.py", "tests/test_auth.py"],
                diff_stats={"files": 3, "additions": 80, "deletions": 12},
            )
            session.add(candidate)
            await session.flush()
            session.add(CandidateScore(
                pr_candidate_id=candidate.id,
                use_case_id=use_case_row.id,
                score=91,
                rationale="verified dependency and consumer paths",
                scored_by="review",
            ))
            await session.commit()

            result = await search.search(
                session, "Python blast radius for a shared auth helper and consumers")
        await engine.dispose()
        return result

    monkeypatch.setattr(search.llm, "complete_json", fail_if_called)
    result = asyncio.run(scenario())

    assert result["intent"]["use_case_slugs"][0] == "security-blast-radius"
    assert result["recommendations"][0]["verified_examples"] == 1
    assert result["recommendations"][0]["effort"] == "ready"
    assert result["results"][0]["verified"] is True
    assert result["results"][0]["demo_effort"] == "quick"
