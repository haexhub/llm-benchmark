"""FR-018 + SC-006: re-runs don't touch existing outputs; new repos are additive.

Uses a fake pipeline (all subprocess/LLM calls stubbed) so it stays hermetic.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from benchmark import pipeline
from benchmark.models import RepoConfig


def _write_run_files(base: Path) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / "diff.patch").write_text("--- a\n+++ b\n")
    (base / "coderabbit.json").write_text('{"schema_version":"1","findings":[]}')
    (base / "gito.json").write_text('{"schema_version":"1","findings":[]}')
    (base / "pr-agent.json").write_text('{"schema_version":"1","findings":[]}')
    (base / "matches.json").write_text('{"schema_version":"1","matches":[]}')


def test_fetch_run_skips_existing(tmp_path: Path) -> None:
    """Pre-existing outputs are never re-fetched or re-run."""
    repo = RepoConfig(owner="alice", name="repo", pr_numbers=[1])
    runs_dir = tmp_path / "runs"
    base = runs_dir / "alice__repo" / "1"
    _write_run_files(base)

    original_mtimes = {p.name: p.stat().st_mtime_ns for p in base.iterdir()}

    with patch("benchmark.pipeline.fetch_diff") as m_diff, \
         patch("benchmark.pipeline.fetch_cr_comments") as m_cr:
        pipeline.do_fetch([repo], runs_dir, force=False, active_repo=None, active_pr=None)
        assert m_diff.call_count == 0
        assert m_cr.call_count == 0

    with patch("benchmark.pipeline._run_gito") as m_g, patch("benchmark.pipeline._run_pragent") as m_p:
        pipeline.do_run([repo], runs_dir, force=False, active_repo=None, active_pr=None)
        assert m_g.call_count == 0
        assert m_p.call_count == 0

    new_mtimes = {p.name: p.stat().st_mtime_ns for p in base.iterdir()}
    assert new_mtimes == original_mtimes


def test_additive_new_repo(tmp_path: Path) -> None:
    """Adding a second repo does not touch the first repo's files."""
    runs_dir = tmp_path / "runs"
    a_base = runs_dir / "alice__repo" / "1"
    _write_run_files(a_base)
    original_a = {p.name: p.stat().st_mtime_ns for p in a_base.iterdir()}

    b_repo = RepoConfig(owner="bob", name="repo", pr_numbers=[7])
    with patch("benchmark.pipeline.fetch_diff", return_value="diff") as m_diff, \
         patch("benchmark.pipeline.fetch_cr_comments", return_value=[]) as m_cr:
        pipeline.do_fetch(
            [RepoConfig(owner="alice", name="repo", pr_numbers=[1]), b_repo],
            runs_dir, force=False, active_repo=None, active_pr=None,
        )
        # Only bob's PR was fetched
        assert m_diff.call_count == 1
        assert m_cr.call_count == 1

    # alice's files unchanged
    new_a = {p.name: p.stat().st_mtime_ns for p in a_base.iterdir()}
    assert new_a == original_a
    # bob's new files exist
    b_base = runs_dir / "bob__repo" / "7"
    assert (b_base / "diff.patch").exists()
    assert (b_base / "coderabbit.json").exists()


def test_force_overwrites(tmp_path: Path) -> None:
    repo = RepoConfig(owner="alice", name="repo", pr_numbers=[1])
    runs_dir = tmp_path / "runs"
    base = runs_dir / "alice__repo" / "1"
    _write_run_files(base)

    with patch("benchmark.pipeline.fetch_diff", return_value="NEW DIFF") as m_diff, \
         patch("benchmark.pipeline.fetch_cr_comments", return_value=[]) as m_cr:
        pipeline.do_fetch([repo], runs_dir, force=True, active_repo=None, active_pr=None)
        assert m_diff.call_count == 1
        assert m_cr.call_count == 1

    assert (base / "diff.patch").read_text() == "NEW DIFF"
