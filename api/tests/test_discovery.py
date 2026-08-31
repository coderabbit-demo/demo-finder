from app.services.discovery import extract_evidence, score_from_evidence
from app.models import UseCase

SAMPLE_REVIEW = """
## Walkthrough
This PR refactors the webhook retry flow...

```mermaid
sequenceDiagram
  participant W as Webhook
```

> Committable suggestion skipped: line range outside diff.

**Assessment against linked issues**
| Objective | Addressed |

Possibly related PRs: #4801
Suggested reviewers: @alice
Ruff (0.4.4) reported 2 issues.
"""


def uc(slug):
    return UseCase(slug=slug, name=slug, detection_heuristics={}, required_config={})


def test_extract_evidence():
    ev = extract_evidence(SAMPLE_REVIEW)
    assert {"walkthrough", "sequence_diagram", "committable", "linked_issues",
            "related_prs", "suggested_reviewers", "tools"} <= ev


def test_evidence_scores_high_with_proof_rationale():
    ev = extract_evidence(SAMPLE_REVIEW)
    score, rationale = score_from_evidence(ev, uc("sequence-diagrams"))
    assert score >= 85
    assert "verified" in rationale


def test_no_evidence_returns_none():
    assert score_from_evidence(set(), uc("sequence-diagrams")) is None
    assert score_from_evidence({"walkthrough"}, uc("sequence-diagrams")) is None


def test_unmapped_use_case_returns_none():
    assert score_from_evidence({"walkthrough"}, uc("atlas-change-stack")) is None


def test_evidence_anchors_deep_link():
    from app.services.discovery import anchor_for_use_case, evidence_anchors
    comments = [
        {"url": "https://github.com/o/r/pull/1#issuecomment-100", "body": "## Walkthrough\n..."},
        {"url": "https://github.com/o/r/pull/1#issuecomment-101", "body": "```mermaid\nsequenceDiagram\n```"},
        {"url": "https://github.com/o/r/pull/1#discussion_r200", "body": "Committable suggestion"},
    ]
    anchors = evidence_anchors(comments)
    assert anchors["sequence_diagram"].endswith("#issuecomment-101")
    assert anchors["committable"].endswith("#discussion_r200")
    assert anchor_for_use_case("sequence-diagrams", anchors).endswith("101")
    assert anchor_for_use_case("summarization", anchors).endswith("100")
    assert anchor_for_use_case("atlas-change-stack", anchors) is None
