"""Regression test: run_cli must kill a timed-out command's whole process
group, not just the directly-tracked PID.

Both gito and pr-agent are launched via `uv tool run --from <pkg> <tool>`.
Verified live: killing only the `uv` wrapper process left the actual `gito`
review running as an orphan (reparented to init) for 15+ minutes past the
timeout, still hitting the LLM endpoint. A plain `subprocess.run(timeout=...)`
only kills its direct child — this test proves the process-group-based fix
also reaches a background-spawned grandchild that a naive single-PID kill
would miss.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from benchmark.tools.base import run_cli


def test_timeout_kills_backgrounded_grandchild(tmp_path: Path) -> None:
    marker = tmp_path / "grandchild_still_running"
    pid_file = tmp_path / "grandchild.pid"
    script = tmp_path / "spawn.sh"
    # Backgrounds a long sleep (the "grandchild") the way `uv tool run` backgrounds
    # the actual tool process, then blocks in the foreground so the parent itself
    # is what run_cli's timeout fires on.
    script.write_text(
        "#!/bin/sh\n"
        f"sh -c 'sleep 20; touch {marker}' &\n"
        f"echo $! > {pid_file}\n"
        "sleep 60\n"
    )
    script.chmod(0o755)

    result = run_cli(["/bin/sh", str(script)], timeout=1)

    assert result.timed_out
    assert result.returncode == -1

    grandchild_pid = int(pid_file.read_text().strip())
    time.sleep(0.5)
    with pytest.raises(ProcessLookupError):
        os.kill(grandchild_pid, 0)  # signal 0: raises if the process is gone
    assert not marker.exists()  # never got the chance to run its 20s sleep to completion


def test_successful_run_returns_normal_result(tmp_path: Path) -> None:
    result = run_cli(["/bin/sh", "-c", "echo hello; exit 0"], timeout=5)
    assert result.ok
    assert result.returncode == 0
    assert "hello" in result.stdout


def test_nonzero_exit_is_not_ok(tmp_path: Path) -> None:
    result = run_cli(["/bin/sh", "-c", "exit 3"], timeout=5)
    assert not result.ok
    assert result.returncode == 3
    assert not result.timed_out
