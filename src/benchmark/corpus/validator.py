"""Validate the public, non-oracle portion of a review corpus."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class CorpusValidationError(ValueError):
    """Raised when a public corpus fixture is incomplete or unreproducible."""


_FORBIDDEN_NAMES = {"ground-truth.yaml", "ground_truth.yaml", "oracle.yaml"}
_FORBIDDEN_DIRECTORIES = {"reproducers", "reference", "oracle"}


@dataclass(frozen=True)
class CorpusValidationReport:
    """The successfully validated public corpus items."""

    item_ids: tuple[str, ...]

    @property
    def item_count(self) -> int:
        return len(self.item_ids)


@dataclass(frozen=True)
class RunnerInput:
    """An Oracle-free, Git-object-free input tree given to a review runner."""

    root: Path
    head_directory: Path
    diff_file: Path
    manifest_file: Path
    policy_file: Path


class SuiteManifest(BaseModel):
    """The executable subset of the published public suite-manifest contract."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: Annotated[str, Field(min_length=1)]
    content_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    status: Literal["draft", "pilot", "released"] | None = None
    modality: Literal["review", "coding"] | None = None
    public_schema_version: Annotated[int, Field(ge=1)] | None = None
    description: str | None = None
    partitions: dict[str, Annotated[int, Field(ge=0)]] | None = None
    oracle_repository: str | None = None


class ItemManifest(BaseModel):
    """The executable subset of the published public item-manifest contract."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")]
    partition: Literal["development", "calibration", "holdout"]
    source: Literal["public", "internal_deidentified", "synthetic"]
    approval_ref: Annotated[str, Field(min_length=1)]
    bundle_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    base_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    head_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    language: Literal["python", "typescript"]
    diff_size_bucket: Literal["small", "medium", "large"]
    difficulty: Literal["easy", "medium", "hard"]


def validate_public_corpus(corpus_root: Path) -> CorpusValidationReport:
    """Validate a public review-corpus suite and return its item inventory."""
    corpus_root = corpus_root.resolve()
    _reject_oracle_material(corpus_root)
    suite_file = corpus_root / "suite.yaml"
    items_directory = corpus_root / "items"
    if not suite_file.is_file():
        raise CorpusValidationError(f"Missing suite manifest: {suite_file}")
    if not items_directory.is_dir():
        raise CorpusValidationError(f"Missing item directory: {items_directory}")

    item_ids: list[str] = []
    item_digests: list[tuple[str, str]] = []
    for item_directory in sorted(path for path in items_directory.iterdir() if path.is_dir()):
        manifest = _load_manifest(item_directory / "manifest.yaml", item_directory.name)
        item_id = manifest.id
        if item_id != item_directory.name:
            raise CorpusValidationError(
                f"{item_directory.name}: manifest id must match its directory name"
            )
        for filename in ("policy.md", "repo.bundle"):
            if not (item_directory / filename).is_file():
                raise CorpusValidationError(f"{item_id}: missing required file {filename}")
        _validate_bundle_digest(item_directory / "repo.bundle", manifest.bundle_sha256, item_id)
        _validate_git_pair(
            item_directory / "repo.bundle",
            manifest.base_sha,
            manifest.head_sha,
            item_id,
        )
        item_ids.append(item_id)
        item_digests.append(
            (
                item_id,
                manifest.bundle_sha256,
                hashlib.sha256((item_directory / "manifest.yaml").read_bytes()).hexdigest(),
                hashlib.sha256((item_directory / "policy.md").read_bytes()).hexdigest(),
            )
        )

    _validate_suite_manifest(suite_file, corpus_root.name, item_digests)
    return CorpusValidationReport(item_ids=tuple(item_ids))


def _validate_bundle_digest(bundle: Path, expected_digest: str, item_id: str) -> None:
    actual_digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    if actual_digest != expected_digest:
        raise CorpusValidationError(f"{item_id}: bundle_sha256 does not match repo.bundle")


def _validate_suite_manifest(
    suite_file: Path, expected_id: str, item_digests: list[tuple[str, str]]
) -> None:
    try:
        document = yaml.safe_load(suite_file.read_text())
    except yaml.YAMLError as error:
        raise CorpusValidationError(f"Invalid suite manifest YAML: {suite_file}") from error
    if not isinstance(document, dict):
        raise CorpusValidationError(f"Suite manifest must be a YAML mapping: {suite_file}")
    try:
        suite = SuiteManifest.model_validate(document)
    except ValidationError as error:
        raise CorpusValidationError(f"Suite manifest violates contract: {error}") from error
    if suite.id != expected_id:
        raise CorpusValidationError("Suite manifest id must match its directory name")
    if suite.content_digest != compute_suite_content_digest(item_digests):
        raise CorpusValidationError("Suite manifest content_digest does not match its items")


def compute_suite_content_digest(item_digests: list[tuple[str, str, str, str]]) -> str:
    """Return a deterministic digest of item, bundle, manifest and policy bytes."""
    content = "\n".join(":".join(record) for record in sorted(item_digests))
    return hashlib.sha256(content.encode()).hexdigest()


def materialize_review_input(corpus_root: Path, item_id: str, output_directory: Path) -> RunnerInput:
    """Create a runner input from public material only, without a `.git` directory."""
    validate_public_corpus(corpus_root)
    corpus_root = corpus_root.resolve()
    item_directory = corpus_root / "items" / item_id
    manifest = _load_manifest(item_directory / "manifest.yaml", item_id)
    if manifest.id != item_id:
        raise CorpusValidationError(f"Unknown corpus item: {item_id}")

    output_directory = output_directory.resolve()
    if output_directory.exists():
        raise CorpusValidationError(f"Runner input output already exists: {output_directory}")
    output_directory.parent.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix="benchmark-review-input-", dir=output_directory.parent) as staging:
        staging_root = Path(staging)
        head_directory = staging_root / "head"
        with TemporaryDirectory(prefix="benchmark-corpus-") as checkout_directory:
            checkout = Path(checkout_directory) / "repo"
            _run_git("clone", "--quiet", str(item_directory / "repo.bundle"), str(checkout), item_id=item_id)
            _extract_commit(checkout, manifest.head_sha, head_directory, item_id)
            changed_paths = [
                path
                for path in _git_output(
                    "diff",
                    "--no-renames",
                    "--name-only",
                    "-z",
                    manifest.base_sha,
                    manifest.head_sha,
                    cwd=checkout,
                    item_id=item_id,
                )
                .decode(errors="surrogateescape")
                .split("\0")
                if path
            ]
            _reject_protected_diff_paths(changed_paths, item_id)
            (staging_root / "diff.patch").write_bytes(
                _git_output(
                    "diff",
                    "--no-renames",
                    "--binary",
                    manifest.base_sha,
                    manifest.head_sha,
                    cwd=checkout,
                    item_id=item_id,
                )
            )
        manifest_file = staging_root / "manifest.yaml"
        policy_file = staging_root / "policy.md"
        shutil.copy2(item_directory / "manifest.yaml", manifest_file)
        shutil.copy2(item_directory / "policy.md", policy_file)
        _reject_oracle_material(staging_root)
        staging_root.rename(output_directory)

    return RunnerInput(
        root=output_directory,
        head_directory=output_directory / "head",
        diff_file=output_directory / "diff.patch",
        manifest_file=output_directory / "manifest.yaml",
        policy_file=output_directory / "policy.md",
    )


def _reject_oracle_material(corpus_root: Path) -> None:
    for path in corpus_root.rglob("*"):
        if path.name in _FORBIDDEN_NAMES or (
            path.is_dir() and path.name in _FORBIDDEN_DIRECTORIES
        ):
            relative_path = path.relative_to(corpus_root)
            raise CorpusValidationError(
                f"Public corpus contains oracle material: {relative_path}"
            )


def _reject_protected_diff_paths(paths: list[str], item_id: str) -> None:
    """Reject a diff that touches a protected path, including one deleted in Head."""
    for raw_path in paths:
        parts = PurePosixPath(raw_path).parts
        if not parts:
            continue
        if parts[-1] in _FORBIDDEN_NAMES or any(part in _FORBIDDEN_DIRECTORIES for part in parts[:-1]):
            raise CorpusValidationError(f"{item_id}: diff touches protected path {raw_path}")


def _load_manifest(manifest_file: Path, item_name: str) -> ItemManifest:
    if not manifest_file.is_file():
        raise CorpusValidationError(f"{item_name}: missing required file manifest.yaml")
    try:
        manifest = yaml.safe_load(manifest_file.read_text())
    except yaml.YAMLError as error:
        raise CorpusValidationError(f"{item_name}: invalid manifest YAML") from error
    if not isinstance(manifest, dict):
        raise CorpusValidationError(f"{item_name}: manifest must be a YAML mapping")
    try:
        return ItemManifest.model_validate(manifest)
    except ValidationError as error:
        raise CorpusValidationError(f"{item_name}: manifest violates contract: {error}") from error


def read_head_file_line_count(bundle: Path, head_sha: str, file_path: str, item_id: str) -> int | None:
    """Return the line count of `file_path` at `head_sha` in `bundle`, or None if absent."""
    with TemporaryDirectory(prefix="benchmark-corpus-") as checkout_directory:
        checkout = Path(checkout_directory) / "repo"
        _run_git("clone", "--quiet", str(bundle), str(checkout), item_id=item_id)
        result = subprocess.run(
            ["git", "show", f"{head_sha}:{file_path}"],
            cwd=checkout,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            return None
        content = result.stdout
        if not content:
            return 0
        return content.count(b"\n") + (0 if content.endswith(b"\n") else 1)


def _validate_git_pair(bundle: Path, base_sha: str, head_sha: str, item_id: str) -> None:
    with TemporaryDirectory(prefix="benchmark-corpus-") as checkout_directory:
        checkout = Path(checkout_directory) / "repo"
        _run_git("clone", "--quiet", str(bundle), str(checkout), item_id=item_id)
        for sha_name, sha in (("base_sha", base_sha), ("head_sha", head_sha)):
            _run_git("cat-file", "-e", f"{sha}^{{commit}}", cwd=checkout, item_id=item_id, field=sha_name)
        _run_git(
            "merge-base",
            "--is-ancestor",
            base_sha,
            head_sha,
            cwd=checkout,
            item_id=item_id,
            field="base_sha",
        )


def _extract_commit(checkout: Path, sha: str, destination: Path, item_id: str) -> None:
    archive = _git_output("archive", "--format=tar", sha, cwd=checkout, item_id=item_id)
    destination.mkdir()
    try:
        with tarfile.open(fileobj=BytesIO(archive)) as tar:
            tar.extractall(destination, filter="data")
    except (tarfile.TarError, OSError) as error:
        raise CorpusValidationError(f"{item_id}: cannot materialize head snapshot") from error


def _git_output(*args: str, cwd: Path, item_id: str) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.decode(errors="replace").strip() or "git command failed"
        raise CorpusValidationError(f"{item_id}: {detail}")
    return result.stdout


def _run_git(
    *args: str,
    cwd: Path | None = None,
    item_id: str,
    field: str | None = None,
) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        label = f" {field}" if field else ""
        detail = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise CorpusValidationError(f"{item_id}:{label} {detail}")
