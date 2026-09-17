from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class SourceOrg(Base):
    __tablename__ = "source_org"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(16), default="github")  # github|gitlab
    org_name: Mapped[str] = mapped_column(String(200))
    connection_type: Mapped[str] = mapped_column(String(16), default="oss")  # oss|personal|org
    included: Mapped[bool] = mapped_column(Boolean, default=True)

    repos: Mapped[list[Repo]] = relationship(back_populates="org", cascade="all, delete-orphan")


class Repo(Base):
    __tablename__ = "repo"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_org_id: Mapped[int] = mapped_column(ForeignKey("source_org.id"))
    full_name: Mapped[str] = mapped_column(String(300), unique=True)
    provider: Mapped[str] = mapped_column(String(16), default="github")
    default_branch: Mapped[str] = mapped_column(String(100), default="main")
    languages: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    has_coderabbit: Mapped[bool] = mapped_column(Boolean, default=False)
    stars: Mapped[int] = mapped_column(Integer, default=0)
    forkable: Mapped[bool] = mapped_column(Boolean, default=True)
    included: Mapped[bool] = mapped_column(Boolean, default=True)
    indexed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    org: Mapped[SourceOrg] = relationship(back_populates="repos")
    candidates: Mapped[list[PrCandidate]] = relationship(back_populates="repo", cascade="all, delete-orphan")


class UseCase(Base):
    __tablename__ = "use_case"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(80), default="review")
    detection_heuristics: Mapped[dict] = mapped_column(JSON, default=dict)
    required_config: Mapped[dict] = mapped_column(JSON, default=dict)
    demo_script_notes: Mapped[str] = mapped_column(Text, default="")
    definition: Mapped[str] = mapped_column(Text, default="")   # docs' own words
    doc_url: Mapped[str] = mapped_column(Text, default="")      # docs.coderabbit.ai link
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    created_from_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class PrCandidate(Base):
    __tablename__ = "pr_candidate"

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repo.id"))
    pr_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(16), default="open")
    files_changed: Mapped[list] = mapped_column(JSON, default=list)
    diff_stats: Mapped[dict] = mapped_column(JSON, default=dict)  # additions, deletions, files, ci_status
    evidence_urls: Mapped[dict] = mapped_column(JSON, default=dict)  # evidence key -> bot comment anchor URL
    crawled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    repo: Mapped[Repo] = relationship(back_populates="candidates")
    scores: Mapped[list[CandidateScore]] = relationship(back_populates="candidate", cascade="all, delete-orphan")


class CandidateScore(Base):
    __tablename__ = "candidate_score"

    id: Mapped[int] = mapped_column(primary_key=True)
    pr_candidate_id: Mapped[int] = mapped_column(ForeignKey("pr_candidate.id"))
    use_case_id: Mapped[int] = mapped_column(ForeignKey("use_case.id"))
    score: Mapped[float] = mapped_column(Float, default=0)
    rationale: Mapped[str] = mapped_column(Text, default="")
    scored_by: Mapped[str] = mapped_column(String(16), default="heuristic")  # heuristic|llm
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    candidate: Mapped[PrCandidate] = relationship(back_populates="scores")
    use_case: Mapped[UseCase] = relationship()


class Example(Base):
    __tablename__ = "example"

    id: Mapped[int] = mapped_column(primary_key=True)
    use_case_id: Mapped[int] = mapped_column(ForeignKey("use_case.id"))
    pr_candidate_id: Mapped[int] = mapped_column(ForeignKey("pr_candidate.id"))
    status: Mapped[str] = mapped_column(String(16), default="candidate")  # candidate|approved|archived
    demo_notes: Mapped[str] = mapped_column(Text, default="")
    formatted_output: Mapped[dict] = mapped_column(JSON, default=dict)

    use_case: Mapped[UseCase] = relationship()
    candidate: Mapped[PrCandidate] = relationship()


class ForkSuggestion(Base):
    __tablename__ = "fork_suggestion"

    id: Mapped[int] = mapped_column(primary_key=True)
    use_case_id: Mapped[int] = mapped_column(ForeignKey("use_case.id"))
    base_repo_id: Mapped[Optional[int]] = mapped_column(ForeignKey("repo.id"), nullable=True)
    base_repo_full_name: Mapped[str] = mapped_column(String(300), default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    suggested_changes: Mapped[list] = mapped_column(JSON, default=list)  # [{path, description, content}]
    suggested_config: Mapped[str] = mapped_column(Text, default="")
    config_kind: Mapped[str] = mapped_column(String(8), default="yaml")  # yaml|ts
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|forked|pr_opened|failed
    fork_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pr_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    use_case: Mapped[UseCase] = relationship()


class SearchLog(Base):
    __tablename__ = "search_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    query: Mapped[str] = mapped_column(Text)
    parsed_intent: Mapped[dict] = mapped_column(JSON, default=dict)
    results: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
