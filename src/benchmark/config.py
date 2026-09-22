from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

from benchmark.models import LiveRepositoryIntegration, RepoConfig


class EnvConfigError(RuntimeError):
    pass


class ReposFile(BaseModel):
    repos: list[RepoConfig]
    live_repositories: list[LiveRepositoryIntegration] = []


def load_env(path: Path | None = None) -> None:
    """Load .env from the project root (or given path). Idempotent."""
    if path is None:
        path = _project_root() / ".env"
    load_dotenv(path, override=False)


def require_env(name: str) -> str:
    val = os.environ.get(name)
    if val is None or val.strip() == "":
        raise EnvConfigError(
            f"Environment variable {name!r} is not set. "
            f"Copy .env.example → .env and fill it in."
        )
    return val


def env(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name)
    if val is None or val.strip() == "":
        return default
    return val


def load_repos(path: Path | None = None) -> list[RepoConfig]:
    if path is None:
        path = _project_root() / "config" / "repos.yaml"
    if not path.exists():
        raise FileNotFoundError(f"repos config not found: {path}")
    with path.open() as fh:
        raw = yaml.safe_load(fh) or {}
    parsed = ReposFile.model_validate(raw)
    return parsed.repos


def load_live_repositories(path: Path | None = None) -> list[LiveRepositoryIntegration]:
    """Load only repositories whose shadow-review opt-in is explicitly enabled."""
    if path is None:
        path = _project_root() / "config" / "repos.yaml"
    if not path.exists():
        raise FileNotFoundError(f"repos config not found: {path}")
    with path.open() as fh:
        raw = yaml.safe_load(fh) or {}
    parsed = ReposFile.model_validate(raw)
    return [integration for integration in parsed.live_repositories if integration.enabled]


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent
