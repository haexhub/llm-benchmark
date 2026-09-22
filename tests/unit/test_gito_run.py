"""Regression test: run_gito_on_pr must pass an absolute --out path.

gito runs with cwd=clone_dir (so its `--what`/`--against` refs resolve inside
the checked-out clone). A relative --out would then resolve against that
clone dir instead of the caller's cwd, doubling the path — verified live: a
completed review ended up at "<clone_dir>/<out_dir>/code-review-report.json"
instead of "<out_dir>/code-review-report.json", so the pipeline never found it.
"""
from __future__ import annotations

from pathlib import Path

from benchmark.tools import gito


def test_run_gito_on_pr_passes_absolute_out_path(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run_cli(cmd, *, timeout, env=None, cwd=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        from benchmark.tools.base import RunResult

        return RunResult(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(gito, "run_cli", fake_run_cli)
    monkeypatch.chdir(tmp_path)

    clone_dir = Path("runs/owner__repo/1/gito-clone")
    out_dir = Path("runs/owner__repo/1/gito-workdir")
    gito.run_gito_on_pr("owner", "repo", 1, "deadbeef", "head-ref", clone_dir, out_dir)

    cmd = captured["cmd"]
    out_idx = cmd.index("--out") + 1
    assert Path(cmd[out_idx]).is_absolute()
    assert Path(cmd[out_idx]) == (tmp_path / out_dir).resolve()


def test_run_gito_on_pr_fetches_the_pinned_head_sha(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run_cli(cmd, *, timeout, env=None, cwd=None):
        calls.append(cmd)
        from benchmark.tools.base import RunResult

        return RunResult(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(gito, "run_cli", fake_run_cli)
    head_sha = "b" * 40
    gito.run_gito_on_pr("owner", "repo", 1, "a" * 40, head_sha, tmp_path / "clone", tmp_path / "out")

    fetch_command = calls[1]
    assert f"{head_sha}:pr-1-head" in fetch_command
    assert "refs/pull/1/head" not in fetch_command
