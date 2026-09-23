from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from benchmark.config import EnvConfigError, load_live_repositories, load_repos, require_env


def test_require_env_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOO_TEST", "bar")
    assert require_env("FOO_TEST") == "bar"


def test_require_env_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FOO_TEST", raising=False)
    with pytest.raises(EnvConfigError):
        require_env("FOO_TEST")


def test_require_env_empty_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOO_TEST", "  ")
    with pytest.raises(EnvConfigError):
        require_env("FOO_TEST")


def test_load_repos_valid(tmp_path: Path) -> None:
    yaml_file = tmp_path / "repos.yaml"
    yaml_file.write_text(
        """
repos:
  - owner: alice
    name: repo-a
    pr_numbers: [1, 2, 3]
  - owner: bob
    name: repo-b
    pr_numbers: [42]
"""
    )
    repos = load_repos(yaml_file)
    assert len(repos) == 2
    assert repos[0].owner == "alice"
    assert repos[0].pr_numbers == [1, 2, 3]
    assert repos[1].slug == "bob__repo-b"


def test_load_repos_empty_list(tmp_path: Path) -> None:
    yaml_file = tmp_path / "repos.yaml"
    yaml_file.write_text("repos: []\n")
    assert load_repos(yaml_file) == []


def test_loads_explicit_live_repository_opt_ins(tmp_path: Path) -> None:
    yaml_file = tmp_path / "repos.yaml"
    yaml_file.write_text(
        """
repos: []
live_repositories:
  - owner: alice
    name: repo-a
    enabled: true
    baseline_wait_minutes: 30
"""
    )

    integrations = load_live_repositories(yaml_file)

    assert len(integrations) == 1
    assert integrations[0].slug == "alice/repo-a"
    assert integrations[0].baseline_wait_minutes == 30


def test_load_repos_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_repos(tmp_path / "nope.yaml")


def test_load_repos_invalid_pr_number(tmp_path: Path) -> None:
    yaml_file = tmp_path / "repos.yaml"
    yaml_file.write_text(
        """
repos:
  - owner: alice
    name: repo-a
    pr_numbers: [1, 0, 3]
"""
    )
    with pytest.raises(ValidationError):
        load_repos(yaml_file)


def test_load_repos_missing_pr_numbers(tmp_path: Path) -> None:
    yaml_file = tmp_path / "repos.yaml"
    yaml_file.write_text(
        """
repos:
  - owner: alice
    name: repo-a
    pr_numbers: []
"""
    )
    with pytest.raises(ValidationError):
        load_repos(yaml_file)
