"""Shared keyword-based category inference for tools whose output has no
structured category field (CodeRabbit's free-text taxonomy, pr-agent's
issue_header/issue_content). gito has structured tags and does its own mapping.
"""
from __future__ import annotations

from benchmark.models import Category


def infer_category(text: str) -> Category:
    t = text.lower()
    if any(k in t for k in ("security", "injection", "xss", "csrf", "auth", "secret")):
        return "security"
    if any(k in t for k in ("perf", "latency", "n+1", "memory")):
        return "perf"
    if any(k in t for k in ("test", "coverage", "assert")):
        return "test"
    if any(k in t for k in ("doc", "docstring", "readme")):
        return "doc"
    if any(
        k in t
        for k in ("bug", "issue", "exception", "error", "crash", "leak", "race", "undefined")
    ):
        return "bug"
    if any(k in t for k in ("style", "naming", "format", "refactor", "cleanup")):
        return "style"
    return "other"
