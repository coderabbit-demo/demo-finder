"""Rubric invariants: banded scale, predicted hard cap, neutral-not-punitive."""
from app.models import PrCandidate, UseCase
from app.services.scoring import PREDICTED_CAP, WEIGHTS, band, score_candidate


def cand(**kw):
    d = dict(repo_id=1, pr_number=1, title="Fix race in webhook retry queue handler",
             url="u", files_changed=["a/webhook.py", "b/queue.py", "c/handler.py"],
             diff_stats={"files": 3, "ci_status": "green"})
    d.update(kw)
    return PrCandidate(**d)


def uc(**h):
    return UseCase(slug="x", name="x", detection_heuristics=h, required_config={})


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_predicted_never_exceeds_cap():
    perfect = uc(keywords=["fix", "race", "webhook"], min_files=2, max_files=10,
                 needs_multi_service=True)
    score, rationale = score_candidate(cand(), perfect, stars=100000)
    assert score <= PREDICTED_CAP
    assert "predicted" in rationale


def test_bands():
    assert band(92) == "demo-ready (verified)"
    assert band(75) == "strong candidate"
    assert band(55) == "usable"
    assert band(30) == "weak"


def test_missing_signals_are_neutral_not_punitive():
    # a use case with no detectors at all should land mid-scale, not zero
    score, _ = score_candidate(cand(), uc())
    assert 40 <= score <= 70


def test_hard_mismatch_scores_low():
    bad = uc(keywords=["terraform"], file_exts=[".tf"], ci_status="red")
    score, _ = score_candidate(cand(), bad)  # python files, green CI, no keyword
    assert score < 50
