from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from benchmark.cli import app


def test_cli_ingests_an_enabled_live_repository(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "repos.yaml"
    config.write_text(
        """
repos: []
live_repositories:
  - owner: alice
    name: repo
    enabled: true
"""
    )
    monkeypatch.chdir(tmp_path)
    with patch(
        "benchmark.cli.fetch_pr_refs", return_value={"base_sha": "a" * 40, "head_sha": "b" * 40}
    ), patch("benchmark.cli.fetch_diff_for_refs", return_value="immutable diff\n"):
        result = CliRunner().invoke(
            app,
            [
                "--config",
                str(config),
                "--runs-dir",
                str(tmp_path / "runs"),
                "live",
                "ingest",
                "--repo",
                "alice/repo",
                "--pr",
                "1",
            ],
        )

    assert result.exit_code == 0, result.output
    assert "Created live observation" in result.output
