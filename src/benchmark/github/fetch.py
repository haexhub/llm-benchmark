"""gh CLI wrapper: pulls PR diff and CodeRabbit comments from GitHub."""
from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

log = logging.getLogger("benchmark.github")

CR_BOT_LOGIN = "coderabbitai[bot]"


def fetch_diff(owner: str, repo: str, pr: int) -> str:
    """Return the unified diff for a PR as a string."""
    proc = subprocess.run(
        ["gh", "pr", "diff", str(pr), "--repo", f"{owner}/{repo}", "--patch"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gh pr diff failed for {owner}/{repo}#{pr}: {proc.stderr.strip()}")
    return proc.stdout


def fetch_diff_for_refs(owner: str, repo: str, base_sha: str, head_sha: str) -> str:
    """Return a diff for an explicit immutable Base/Head pair, never a mutable PR ref."""
    compare_endpoint = f"repos/{owner}/{repo}/compare/{base_sha}...{head_sha}"
    proc = subprocess.run(
        ["gh", "api", "-H", "Accept: application/vnd.github.v3.diff", compare_endpoint],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"gh compare diff failed for {owner}/{repo} {base_sha}...{head_sha}: {proc.stderr.strip()}"
        )
    return proc.stdout


def fetch_pr_refs(owner: str, repo: str, pr: int) -> dict[str, str]:
    """Return {base_sha, head_sha, head_ref} for a PR (used to review it in a local clone)."""
    proc = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/pulls/{pr}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gh api pulls/{pr} failed for {owner}/{repo}: {proc.stderr.strip()}")
    data = json.loads(proc.stdout)
    return {
        "base_sha": data["base"]["sha"],
        "head_sha": data["head"]["sha"],
        "head_ref": data["head"]["ref"],
    }


def fetch_cr_comments(owner: str, repo: str, pr: int) -> list[dict[str, Any]]:
    """Return the union of CR-authored comments from all three GitHub endpoints."""
    endpoints = [
        f"repos/{owner}/{repo}/pulls/{pr}/comments",  # line-level review comments
        f"repos/{owner}/{repo}/pulls/{pr}/reviews",  # review summaries
        f"repos/{owner}/{repo}/issues/{pr}/comments",  # general issue comments
    ]
    result: list[dict[str, Any]] = []
    for endpoint in endpoints:
        proc = subprocess.run(
            ["gh", "api", "--paginate", endpoint],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            log.warning("gh api failed for %s: %s", endpoint, proc.stderr.strip()[:200])
            continue
        # gh api --paginate concatenates JSON arrays; each page starts with '['
        # We stream-decode to survive that.
        for chunk in _parse_ghapi_pages(proc.stdout):
            for item in chunk:
                if not isinstance(item, dict):
                    continue
                user = (item.get("user") or {}).get("login")
                if user == CR_BOT_LOGIN:
                    result.append(item)
    return result


def _parse_ghapi_pages(raw: str) -> list[list[dict[str, Any]]]:
    """gh api --paginate emits multiple JSON arrays concatenated. Parse them all."""
    decoder = json.JSONDecoder()
    idx = 0
    text = raw.strip()
    out: list[list[dict[str, Any]]] = []
    while idx < len(text):
        # Skip whitespace between arrays
        while idx < len(text) and text[idx].isspace():
            idx += 1
        if idx >= len(text):
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError as exc:
            log.warning("failed to parse gh api output at pos %d: %s", idx, exc)
            break
        if isinstance(obj, list):
            out.append(obj)
        elif isinstance(obj, dict):
            out.append([obj])
        idx = end
    return out
