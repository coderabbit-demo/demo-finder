"""GitHub REST client: crawl open PRs, fork, branch, commit, open PR.

Uses plain httpx against api.github.com — no heavy SDK. Requires GITHUB_TOKEN
for real calls; crawl raises a clear error without one.
"""
from __future__ import annotations

import base64
from typing import Any

import httpx

from ..config import settings

API = "https://api.github.com"


def _client() -> httpx.AsyncClient:
    if not settings.github_token:
        raise RuntimeError("GITHUB_TOKEN is not configured — set it in .env (DEV_MODE fixtures work without it)")
    return httpx.AsyncClient(
        base_url=API, timeout=30,
        headers={"Authorization": f"Bearer {settings.github_token}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"},
    )


async def list_open_prs(full_name: str, limit: int = 30) -> list[dict[str, Any]]:
    """Open PRs with files + CI status, normalized for PrCandidate."""
    async with _client() as gh:
        r = await gh.get(f"/repos/{full_name}/pulls", params={"state": "open", "per_page": limit})
        r.raise_for_status()
        out = []
        for pr in r.json():
            num = pr["number"]
            files_r = await gh.get(f"/repos/{full_name}/pulls/{num}/files", params={"per_page": 100})
            files = [f["filename"] for f in files_r.json()] if files_r.status_code == 200 else []
            ci = "unknown"
            status_r = await gh.get(f"/repos/{full_name}/commits/{pr['head']['sha']}/check-runs")
            if status_r.status_code == 200:
                runs = status_r.json().get("check_runs", [])
                if runs:
                    ci = "red" if any(c.get("conclusion") == "failure" for c in runs) else "green"
            out.append({
                "pr_number": num,
                "title": pr["title"],
                "url": pr["html_url"],
                "files_changed": files,
                "diff_stats": {"additions": pr.get("additions", 0), "deletions": pr.get("deletions", 0),
                               "files": len(files), "ci_status": ci},
            })
        return out


BOT_LOGINS = {"coderabbitai", "coderabbitai[bot]"}


async def search_bot_reviewed_prs(phrase: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
    """GitHub-wide: open PRs that coderabbitai[bot] has commented on, optionally
    filtered by a phrase appearing in the comments."""
    q = "commenter:coderabbitai[bot] is:pr is:open archived:false"
    if phrase:
        q += f' "{phrase}" in:comments'
    async with _client() as gh:
        r = await gh.get("/search/issues", params={"q": q, "per_page": limit, "sort": "updated"})
        r.raise_for_status()
        out = []
        for item in r.json().get("items", []):
            # repository_url = https://api.github.com/repos/{owner}/{repo}
            full_name = "/".join(item["repository_url"].split("/")[-2:])
            out.append({"full_name": full_name, "pr_number": item["number"],
                        "title": item["title"], "url": item["html_url"]})
        return out


_SNAPSHOT_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      additions deletions
      files(first: 100) { nodes { path } }
      comments(first: 100) { nodes { author { login } body url } }
      reviewThreads(first: 50) { nodes { comments(first: 20) { nodes { author { login } body url } } } }
      commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
    }
  }
}"""


async def get_pr_snapshot(full_name: str, pr_number: int) -> dict[str, Any]:
    """Files + stats + CI + every coderabbitai[bot] comment — ONE GraphQL call
    (vs 4 REST calls). Falls back to REST on any GraphQL failure."""
    owner, name = full_name.split("/", 1)
    try:
        async with _client() as gh:
            r = await gh.post("/graphql", json={
                "query": _SNAPSHOT_QUERY,
                "variables": {"owner": owner, "name": name, "number": pr_number}})
            r.raise_for_status()
            pr = r.json()["data"]["repository"]["pullRequest"]
        files = [n["path"] for n in pr["files"]["nodes"]]
        bot_comments = []
        thread_comments = [c for t in pr["reviewThreads"]["nodes"] for c in t["comments"]["nodes"]]
        for c in pr["comments"]["nodes"] + thread_comments:
            if ((c.get("author") or {}).get("login") or "").lower() in BOT_LOGINS:
                bot_comments.append({"url": c.get("url", ""), "body": c.get("body", "")})
        rollup = (pr["commits"]["nodes"] or [{}])[0].get("commit", {}).get("statusCheckRollup")
        ci = {"SUCCESS": "green", "FAILURE": "red", "ERROR": "red"}.get(
            (rollup or {}).get("state", ""), "unknown")
        return {
            "files_changed": files,
            "diff_stats": {"additions": pr["additions"], "deletions": pr["deletions"],
                           "files": len(files), "ci_status": ci},
            "bot_comments": bot_comments,
            "bot_review_text": "\n\n".join(c["body"] for c in bot_comments),
        }
    except Exception:
        return await _get_pr_snapshot_rest(full_name, pr_number)


async def _get_pr_snapshot_rest(full_name: str, pr_number: int) -> dict[str, Any]:
    """REST fallback: files + stats + every comment coderabbitai[bot] left."""
    async with _client() as gh:
        files_r = await gh.get(f"/repos/{full_name}/pulls/{pr_number}/files", params={"per_page": 100})
        files = [f["filename"] for f in files_r.json()] if files_r.status_code == 200 else []
        pr_r = await gh.get(f"/repos/{full_name}/pulls/{pr_number}")
        pr = pr_r.json() if pr_r.status_code == 200 else {}
        bot_comments = []  # [{url, body}] — url anchors straight to the comment on GitHub
        for path in (f"/repos/{full_name}/issues/{pr_number}/comments",
                     f"/repos/{full_name}/pulls/{pr_number}/comments"):
            c_r = await gh.get(path, params={"per_page": 100})
            if c_r.status_code == 200:
                bot_comments += [{"url": c.get("html_url", ""), "body": c["body"]}
                                 for c in c_r.json()
                                 if (c.get("user") or {}).get("login", "").lower() in BOT_LOGINS]
        return {
            "files_changed": files,
            "diff_stats": {"additions": pr.get("additions", 0), "deletions": pr.get("deletions", 0),
                           "files": len(files), "ci_status": "unknown"},
            "bot_comments": bot_comments,
            "bot_review_text": "\n\n".join(c["body"] for c in bot_comments),
        }


async def list_org_repos(org_name: str, limit: int = 100) -> list[dict[str, Any]]:
    """All repos visible to the token under an org (falls back to user account)."""
    async with _client() as gh:
        r = await gh.get(f"/orgs/{org_name}/repos", params={"per_page": limit, "sort": "pushed"})
        if r.status_code == 404:
            r = await gh.get(f"/users/{org_name}/repos", params={"per_page": limit, "sort": "pushed"})
        r.raise_for_status()
        return [{
            "full_name": d["full_name"],
            "default_branch": d["default_branch"],
            "languages": [d["language"].lower()] if d.get("language") else [],
            "stars": d["stargazers_count"],
            "forkable": d.get("allow_forking", True) and not d["archived"],
        } for d in r.json()]


async def get_repo_meta(full_name: str) -> dict[str, Any]:
    async with _client() as gh:
        r = await gh.get(f"/repos/{full_name}")
        r.raise_for_status()
        data = r.json()
        has_cr = False
        cfg = await gh.get(f"/repos/{full_name}/contents/.coderabbit.yaml")
        has_cr = cfg.status_code == 200
        return {"default_branch": data["default_branch"], "stars": data["stargazers_count"],
                "language": (data.get("language") or "").lower(), "fork": data["fork"],
                "license": (data.get("license") or {}).get("spdx_id"), "has_coderabbit": has_cr}


async def fork_and_open_pr(base_full_name: str, branch: str, files: list[dict],
                           pr_title: str, pr_body: str) -> dict[str, str]:
    """Fork base repo to the token owner, commit `files` [{path, content}] on a
    branch, open a PR against the fork's own default branch (so CodeRabbit
    reviews inside the fork)."""
    async with _client() as gh:
        me = (await gh.get("/user")).json()["login"]
        fork_r = await gh.post(f"/repos/{base_full_name}/forks")
        fork_r.raise_for_status()
        fork = fork_r.json()
        fork_full, default = fork["full_name"], fork["default_branch"]

        # base sha (fork may take a moment to be ready — retry once handled by caller if needed)
        ref = await gh.get(f"/repos/{fork_full}/git/ref/heads/{default}")
        ref.raise_for_status()
        base_sha = ref.json()["object"]["sha"]
        await gh.post(f"/repos/{fork_full}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": base_sha})

        for f in files:
            existing = await gh.get(f"/repos/{fork_full}/contents/{f['path']}", params={"ref": branch})
            payload: dict[str, Any] = {
                "message": f"demo: {f['path']}",
                "content": base64.b64encode(f["content"].encode()).decode(),
                "branch": branch,
            }
            if existing.status_code == 200:
                payload["sha"] = existing.json()["sha"]
            put = await gh.put(f"/repos/{fork_full}/contents/{f['path']}", json=payload)
            put.raise_for_status()

        pr = await gh.post(f"/repos/{fork_full}/pulls",
                           json={"title": pr_title, "body": pr_body, "head": branch, "base": default})
        pr.raise_for_status()
        return {"fork_url": fork["html_url"], "pr_url": pr.json()["html_url"], "owner": me}
