"""Candidate scoring — engineering-standard rubric.

One scale, three producers, non-overlapping bands:

  85–98  VERIFIED   (scored_by: review)  — the capability is provably present in
                     CodeRabbit's actual review on the PR. 85 base + breadth bonus.
                     Produced by discovery.score_from_evidence. Never predictive.
  ≤ 84   PREDICTED  (scored_by: heuristic | llm) — weighted-criteria estimate of
                     how well the PR *would* demo the capability. Hard-capped at
                     84 so a prediction can never outrank proof.
  100 / 99 reserved (future: verified + human-flagged).

Bands for interpretation (UI + demos):
  ≥85 demo-ready (verified) · 70–84 strong candidate · 50–69 usable · <50 weak

The predicted score is a weighted sum of orthogonal normalized criteria — the
standard "weighted scoring model". Weights are explicit, sum to 1, and live in
WEIGHTS so tuning is a config change, not a rewrite:

  capability_fit  0.55  use-case-specific detectors (keywords, extensions, CI
                        state, actor count, linked issue, module shape)
  size_fit        0.20  diff size within the use case's demo-able window
  repo_quality    0.15  realistic, active project (log-scaled stars)
  freshness       0.10  recency of the PR (neutral 0.5 when unknown)

Each criterion is 0..1; missing signals score neutral (0.5), never punitive,
so absence of data doesn't masquerade as evidence of a bad candidate.
"""
from __future__ import annotations

import math
import re

from ..models import PrCandidate, UseCase
from . import llm

PREDICTED_CAP = 84.0
WEIGHTS = {"capability_fit": 0.55, "size_fit": 0.20, "repo_quality": 0.15, "freshness": 0.10}

_MULTI_SERVICE_HINTS = ("webhook", "queue", "worker", "handler", "consumer", "producer", "service", "client", "api")
_ISSUE_LINK = re.compile(r"(closes|fixes|resolves)\s+#\d+|[A-Z]{2,10}-\d+", re.IGNORECASE)


def band(score: float) -> str:
    if score >= 85: return "demo-ready (verified)"
    if score >= 70: return "strong candidate"
    if score >= 50: return "usable"
    return "weak"


def _capability_fit(cand: PrCandidate, h: dict, notes: list[str]) -> float:
    """Mean of the use case's applicable detectors, each 0..1."""
    files = cand.files_changed or []
    stats = cand.diff_stats or {}
    title = (cand.title or "").lower()
    parts: list[float] = []

    if kws := h.get("keywords"):
        hits = [k for k in kws if k.lower() in title]
        parts.append(min(1.0, len(hits) / 2))
        notes.append(f"keywords {len(hits)}/{len(kws)}" + (f" ({', '.join(hits[:3])})" if hits else ""))
    if exts := h.get("file_exts"):
        matched = sum(1 for f in files if any(f.endswith(e) for e in exts))
        parts.append(1.0 if matched else 0.0)
        notes.append(f"{matched} files match {'/'.join(exts)}")
    if h.get("ci_status") == "red":
        ci = stats.get("ci_status", "unknown")
        parts.append(1.0 if ci == "red" else 0.5 if ci == "unknown" else 0.0)
        notes.append(f"CI {ci} (wants red)")
    if h.get("needs_multi_service"):
        actors = {hint for f in files for hint in _MULTI_SERVICE_HINTS if hint in f.lower()}
        parts.append(min(1.0, len(actors) / 3))
        notes.append(f"{len(actors)} service actors")
    if h.get("needs_linked_issue"):
        linked = bool(_ISSUE_LINK.search(cand.title or ""))
        parts.append(1.0 if linked else 0.0)
        notes.append("linked issue" if linked else "no linked issue")
    if h.get("prefers_new_module"):
        logic = [f for f in files if "test" not in f.lower()]
        has_tests = any("test" in f.lower() for f in files)
        parts.append(1.0 if logic and not has_tests else 0.3)
        notes.append("logic without tests" if logic and not has_tests else "tests present")

    return sum(parts) / len(parts) if parts else 0.5  # no detectors -> neutral


def _size_fit(cand: PrCandidate, h: dict, notes: list[str]) -> float:
    n = (cand.diff_stats or {}).get("files", len(cand.files_changed or []))
    lo, hi = h.get("min_files"), h.get("max_files")
    if lo is None and hi is None:
        return 0.7  # mild preference for any reviewed size
    lo = lo or 1
    hi = hi or max(lo, 30)
    if lo <= n <= hi:
        notes.append(f"{n} files in window [{lo},{hi}]")
        return 1.0
    dist = (lo - n) if n < lo else (n - hi)
    notes.append(f"{n} files outside [{lo},{hi}]")
    return max(0.0, 1.0 - dist / 10)


def _repo_quality(stars: int | None, notes: list[str]) -> float:
    if stars is None:
        return 0.5
    q = min(1.0, math.log10(stars + 1) / 4)  # 10k stars -> 1.0
    notes.append(f"repo ★{stars}")
    return q


def score_candidate(cand: PrCandidate, uc: UseCase, stars: int | None = None) -> tuple[float, str]:
    """Predicted score (≤84) with a criterion-by-criterion rationale."""
    h = uc.detection_heuristics or {}
    notes: list[str] = []
    criteria = {
        "capability_fit": _capability_fit(cand, h, notes),
        "size_fit": _size_fit(cand, h, notes),
        "repo_quality": _repo_quality(stars, notes),
        "freshness": 0.5,  # neutral until PR updated_at is captured
    }
    raw = 100 * sum(WEIGHTS[k] * v for k, v in criteria.items())
    score = round(min(PREDICTED_CAP, max(0.0, raw)), 1)
    detail = " · ".join(f"{k} {v:.2f}" for k, v in criteria.items())
    rationale = f"predicted [{band(score)}]: {detail}" + (f" — {'; '.join(notes)}" if notes else "")
    return score, rationale


async def llm_refine(cand: PrCandidate, uc: UseCase, heuristic_score: float) -> tuple[float, str] | None:
    """Optional LLM re-score. Still a prediction, so still capped at 84."""
    result = await llm.complete_json(
        system=("You score how good an open PR is as a live demo of a specific CodeRabbit capability. "
                "This is a PREDICTION (the capability is not yet verified on the PR), so score 0-84. "
                "Rubric: 70-84 strong candidate, 50-69 usable, <50 weak. Return "
                '{"score": 0-84, "rationale": "1-2 sentences, demo-presenter voice"}.'),
        user=(f"Capability: {uc.name}\nDocs definition: {uc.definition}\n"
              f"Heuristics: {uc.detection_heuristics}\n"
              f"PR title: {cand.title}\nFiles: {cand.files_changed}\nStats: {cand.diff_stats}\n"
              f"Rubric prior: {heuristic_score}"),
        max_tokens=300,
    )
    if not isinstance(result, dict) or "score" not in result:
        return None
    score = min(PREDICTED_CAP, float(result["score"]))
    return score, f"predicted [{band(score)}]: {result.get('rationale', '')}"
