from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from benchmark.corpus import run_protected_reproducer, verify_reproducer_determinism
from benchmark.corpus.reproducer import ReproducerResult


def test_runs_a_protected_reproducer_against_a_read_only_fixture(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    (fixture_root / "service.py").write_text("def answer() -> int:\n    return 42\n")
    reproducer = tmp_path / "reproducer.sh"
    reproducer.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        'test -f "$1/service.py"\n'
        'test "$(cat "$1/service.py")" = "def answer() -> int:\n    return 42"\n'
    )

    result = run_protected_reproducer(reproducer, fixture_root)

    assert result.passed is True
    assert result.network_isolated is True
    assert result.fixture_sha256


def test_rejects_a_reproducer_that_attempts_to_mutate_the_fixture(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    (fixture_root / "service.py").write_text("def answer() -> int:\n    return 42\n")
    reproducer = tmp_path / "reproducer.sh"
    reproducer.write_text('#!/bin/sh\nset -eu\necho tampered > "$1/service.py"\n')

    result = run_protected_reproducer(reproducer, fixture_root)

    assert result.passed is False
    assert (fixture_root / "service.py").read_text().endswith("return 42\n")


def test_exposes_python_under_the_reproducer_contract_name(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    reproducer = tmp_path / "reproducer.sh"
    reproducer.write_text('#!/bin/sh\nset -eu\npython -c "assert 2 + 2 == 4"\n')

    result = run_protected_reproducer(reproducer, fixture_root)

    assert result.passed is True


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_exposes_node_from_a_scoped_toolchain_mount(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    reproducer = tmp_path / "reproducer.sh"
    reproducer.write_text('#!/bin/sh\nset -eu\nnode -e "process.exit(0)"\n')

    result = run_protected_reproducer(reproducer, fixture_root)

    assert result.passed is True


def test_verifies_a_deterministic_reproducer_across_repeated_runs(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    (fixture_root / "service.py").write_text("def answer() -> int:\n    return 42\n")
    reproducer = tmp_path / "reproducer.sh"
    reproducer.write_text('#!/bin/sh\nset -eu\npython -c "assert 2 + 2 == 4"\n')

    result = verify_reproducer_determinism(reproducer, fixture_root, runs=3)

    assert result.deterministic is True
    assert result.run_count == 3
    assert len(result.evidence_digest) == 64


def test_flags_a_flaky_reproducer_as_non_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    reproducer = tmp_path / "reproducer.sh"
    reproducer.write_text("#!/bin/sh\nset -eu\ntrue\n")
    outcomes = iter([True, False, True])
    monkeypatch.setattr(
        "benchmark.corpus.reproducer.run_protected_reproducer",
        lambda *_args, **_kwargs: ReproducerResult(
            passed=next(outcomes),
            network_isolated=True,
            exit_code=0,
            duration_seconds=0.0,
            fixture_sha256="a" * 64,
            stdout="",
            stderr="",
            timed_out=False,
        ),
    )

    result = verify_reproducer_determinism(reproducer, fixture_root, runs=3)

    assert result.deterministic is False


def test_records_a_timeout_as_failed_evidence(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    reproducer = tmp_path / "reproducer.sh"
    reproducer.write_text("#!/bin/sh\nset -eu\nsleep 1\n")

    result = run_protected_reproducer(reproducer, fixture_root, timeout_seconds=0.01)

    assert result.passed is False
    assert result.timed_out is True
