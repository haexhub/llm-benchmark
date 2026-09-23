"""Protected, post-run execution of deterministic Gold reproducers."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

from .validator import CorpusValidationError


@dataclass(frozen=True)
class DeterminismResult:
    """Whether a reproducer passed identically across repeated isolated runs."""

    deterministic: bool
    run_count: int
    evidence_digest: str


@dataclass(frozen=True)
class ReproducerResult:
    """Recorded result of one isolated protected reproducer execution."""

    passed: bool
    network_isolated: bool
    exit_code: int
    duration_seconds: float
    fixture_sha256: str
    stdout: str
    stderr: str
    timed_out: bool


def run_protected_reproducer(
    reproducer: Path,
    fixture_root: Path,
    *,
    timeout_seconds: float = 60,
) -> ReproducerResult:
    """Run one protected reproducer against an Oracle-free, read-only fixture tree."""
    if shutil.which("bwrap") is None:
        raise CorpusValidationError("bubblewrap (bwrap) is required for protected reproducer execution")
    reproducer = reproducer.resolve()
    fixture_root = fixture_root.resolve()
    if not reproducer.is_file():
        raise CorpusValidationError(f"Missing protected reproducer: {reproducer}")
    if not fixture_root.is_dir():
        raise CorpusValidationError(f"Missing fixture root: {fixture_root}")
    if any(path.name == ".git" for path in fixture_root.rglob(".git")):
        raise CorpusValidationError("Fixture root must not contain Git objects")

    fixture_sha256 = _digest_fixture(fixture_root)
    with TemporaryDirectory(prefix="benchmark-reproducer-") as script_directory:
        script_path = Path(script_directory) / "reproducer.sh"
        shutil.copy2(reproducer, script_path)
        command = _sandbox_command(script_path, fixture_root)
        started_at = monotonic()
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
            exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
            timed_out = False
        except subprocess.TimeoutExpired as error:
            exit_code = 124
            stdout = _timeout_output(error.stdout)
            stderr = _timeout_output(error.stderr)
            timed_out = True
        duration_seconds = monotonic() - started_at

    return ReproducerResult(
        passed=exit_code == 0,
        network_isolated=True,
        exit_code=exit_code,
        duration_seconds=duration_seconds,
        fixture_sha256=fixture_sha256,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
    )


def verify_reproducer_determinism(
    reproducer: Path, fixture_root: Path, *, runs: int = 3
) -> DeterminismResult:
    """Run a protected reproducer repeatedly and digest the evidence for curator sign-off."""
    if runs < 1:
        raise CorpusValidationError("runs must be at least 1")
    results = [run_protected_reproducer(reproducer, fixture_root) for _ in range(runs)]
    evidence = [_evidence_record(result) for result in results]
    deterministic = all(result["passed"] for result in evidence) and all(
        result == evidence[0] for result in evidence[1:]
    )
    evidence_digest = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return DeterminismResult(
        deterministic=deterministic, run_count=runs, evidence_digest=evidence_digest
    )


def _evidence_record(result: ReproducerResult) -> dict[str, object]:
    """Return the stable outcome fields used to compare repeated executions."""
    return {
        "exit_code": result.exit_code,
        "fixture_sha256": result.fixture_sha256,
        "network_isolated": result.network_isolated,
        "passed": result.passed,
        "stderr": result.stderr,
        "stdout": result.stdout,
        "timed_out": result.timed_out,
    }


def _sandbox_command(script_path: Path, fixture_root: Path) -> list[str]:
    command = [
        "bwrap",
        "--die-with-parent",
        "--new-session",
        "--unshare-net",
        "--clearenv",
        "--setenv",
        "PATH",
        "/tools/node/bin:/tools:/usr/bin:/bin",
        "--setenv",
        "LANG",
        "C.UTF-8",
        "--ro-bind",
        "/usr",
        "/usr",
        "--symlink",
        "usr/bin",
        "/bin",
        "--symlink",
        "usr/lib",
        "/lib",
        "--symlink",
        "usr/lib64",
        "/lib64",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--dir",
        "/tools",
        "--symlink",
        "/usr/bin/python3",
        "/tools/python",
    ]
    node_binary = shutil.which("node")
    if node_binary:
        node_root = Path(node_binary).resolve().parent.parent
        if node_root != Path("/usr"):
            command.extend(["--ro-bind", str(node_root), "/tools/node"])
    command.extend([
        "--ro-bind",
        str(fixture_root),
        "/fixture",
        "--ro-bind",
        str(script_path.parent),
        "/evaluator",
        "--chdir",
        "/fixture",
        "/bin/sh",
        "/evaluator/reproducer.sh",
        "/fixture",
    ])
    return command


def _digest_fixture(fixture_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(path for path in fixture_root.rglob("*") if path.is_file()):
        relative_path = path.relative_to(fixture_root).as_posix().encode()
        digest.update(relative_path)
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _timeout_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode(errors="replace")
    return output
