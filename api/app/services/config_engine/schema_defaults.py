"""Subset of CodeRabbit schema defaults relevant to v1's generated configs.

The universal fallback tier — final fill in get_repo_config(). Extend as the
fork engine grows; v2 Config Lab should load the full published schema.
"""

SCHEMA_DEFAULTS: dict = {
    "language": "en-US",
    "tone_instructions": "",
    "reviews": {
        "profile": "chill",
        "request_changes_workflow": False,
        "high_level_summary": True,
        "changed_files_summary": True,
        "sequence_diagrams": True,
        "suggested_changes": True,
        "suggested_reviewers": True,
        "poem": True,
        "review_status": True,
        "commit_status": True,
        "path_filters": [],
        "path_instructions": [],
        "pre_merge_checks": {},
        "tools": {},
    },
    "chat": {"art": True, "auto_reply": True},
    "knowledge_base": {
        "learnings": {"scope": "auto"},
        "issues": {"scope": "auto"},
        "pull_requests": {"scope": "auto"},
        "code_guidelines": {"enabled": True},
        "web_search": {"enabled": True},
        "mcp": {"usage": "auto"},
    },
    "code_generation": {
        "docstrings": {"language": "en-US"},
        "unit_tests": {"path_instructions": []},
    },
}
