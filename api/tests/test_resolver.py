"""Worked example from the Indeed spec — the resolution trace must match exactly."""
from app.services.config_engine.resolver import (
    ConfigNode, apply_overrides, fill_gaps, get_repo_config, merge_lists, resolve_with_trace,
)

SCHEMA = {"reviews": {"profile": "chill", "review_status": True, "poem": True,
                      "commit_status": True}, "chat": {"art": True}}


def build_tree():
    workspace = ConfigNode(file_path="workspace", config={
        "reviews": {"poem": False, "commit_status": True}, "chat": {"art": False}})
    central = ConfigNode(file_path="group/coderabbit", parent=workspace, config={
        "reviews": {"review_status": False, "poem": False}})
    repo = ConfigNode(file_path="group/team/svc", parent=central, config={
        "reviews": {"profile": "assertive"}})
    return repo


def test_worked_example():
    resolved = get_repo_config(build_tree(), SCHEMA,
                               global_overrides={"reviews": {"commit_status": False}})
    r = resolved["reviews"]
    assert r["commit_status"] is False          # global override beats workspace True
    assert r["profile"] == "assertive"          # repo wins
    assert r["review_status"] is False          # central inherited WITHOUT any flag — the fix
    assert r["poem"] is False                   # central (first writer above repo)
    assert resolved["chat"]["art"] is False     # workspace fills the gap


def test_won_by_trace():
    trace = resolve_with_trace(build_tree(), SCHEMA,
                               global_overrides={"reviews": {"commit_status": False}})["won_by"]
    assert trace["reviews.commit_status"] == "global override"
    assert trace["reviews.profile"] == "group/team/svc"
    assert trace["reviews.review_status"] == "group/coderabbit"
    assert trace["chat.art"] == "workspace"


def test_inheritance_false_stops_walk():
    repo = build_tree()
    repo.inherits = False
    resolved = get_repo_config(repo, SCHEMA)
    assert resolved["reviews"]["review_status"] is True   # central NOT pulled; schema default
    assert resolved["reviews"]["profile"] == "assertive"  # own keys kept


def test_remote_config_is_exclusive_redirect():
    remote = ConfigNode(file_path="remote", config={"reviews": {"profile": "assertive"}})
    repo = build_tree()
    repo.remote = remote
    resolved = get_repo_config(repo, SCHEMA)
    assert resolved["reviews"]["poem"] is True   # central/workspace NOT inherited
    assert resolved["reviews"]["profile"] == "assertive"


def test_includes_last_listed_wins():
    inc1 = ConfigNode(file_path="inc1", config={"reviews": {"poem": True}})
    inc2 = ConfigNode(file_path="inc2", config={"reviews": {"poem": False}})
    repo = ConfigNode(file_path="repo", config={}, includes=[inc1, inc2])
    assert get_repo_config(repo, SCHEMA)["reviews"]["poem"] is False


def test_list_merge_identity_and_override_replaces():
    base = [{"path": "**/*.sql", "instructions": "child"}]
    src = [{"path": "**/*.sql", "instructions": "parent"}, {"path": "**/*.py", "instructions": "p"}]
    merged = merge_lists(base, src)
    assert merged[0]["instructions"] == "child" and len(merged) == 2
    assert apply_overrides({"a": [1, 2]}, {"a": [3]})["a"] == [3]  # enforced list REPLACES
    assert fill_gaps({"a": 1}, {"a": 2, "b": 3}) == {"a": 1, "b": 3}
