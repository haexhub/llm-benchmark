"""Common subprocess handling: timeout, stdout/stderr capture, env merging."""
from __future__ import annotations

import contextlib
import logging
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("benchmark.tools")


@dataclass
class RunResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def run_cli(
    cmd: list[str],
    *,
    timeout: int,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    cancel_event: threading.Event | None = None,
) -> RunResult:
    """Run `cmd`, killing its whole process group on timeout.

    `subprocess.run(..., timeout=...)` only kills the direct child. Both gito
    and pr-agent are launched via `uv tool run --from <pkg> <tool> ...`, which
    does not forward signals to the tool process it spawns — verified live: a
    gito review outlived its killed `uv tool run` wrapper by 15+ minutes,
    running on as an orphan (reparented to init) and continuing to hit the
    LLM endpoint. `start_new_session=True` puts the whole tree in its own
    process group so a timeout can take all of it out via `os.killpg`.
    """
    log.debug("running: %s", " ".join(cmd))
    if cancel_event is not None and cancel_event.is_set():
        return RunResult(returncode=-1, stdout="", stderr="cancelled")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=cwd,
        start_new_session=True,
    )
    deadline = time.monotonic() + timeout
    while True:
        if cancel_event is not None and cancel_event.is_set():
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            stdout, stderr = proc.communicate()
            return RunResult(returncode=-1, stdout=stdout or "", stderr=stderr or "cancelled")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            log.warning("timeout after %ss for %s — killing process group", timeout, cmd[0])
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            stdout, stderr = proc.communicate()
            return RunResult(returncode=-1, stdout=stdout or "", stderr=stderr or "", timed_out=True)
        try:
            stdout, stderr = proc.communicate(
                timeout=min(remaining, 0.1) if cancel_event is not None else remaining
            )
        except subprocess.TimeoutExpired:
            continue
        return RunResult(returncode=proc.returncode, stdout=stdout, stderr=stderr)
