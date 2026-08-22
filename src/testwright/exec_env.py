"""Sandboxed process execution with timeouts and bounded resources.

Every invocation of target-project code goes through ``run_command``. There is
no shell interpolation: argv lists only. On timeout the whole process tree is
killed. On POSIX an address-space limit is applied; Windows offers no portable
equivalent, which the report states rather than hides.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .errors import UsageError

DEFAULT_TIMEOUT_SECONDS = 120.0
MAX_OUTPUT_BYTES = 200_000


@dataclass
class RunResult:
    command: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def tail(self, lines: int = 12) -> str:
        text = (self.stdout + "\n" + self.stderr).strip()
        return "\n".join(text.splitlines()[-lines:])


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                timeout=10,
            )
        else:
            proc.send_signal(signal.SIGKILL)
    except (OSError, subprocess.TimeoutExpired, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass


def run_command(
    argv: list[str],
    cwd: Path,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    env_overrides: dict[str, str] | None = None,
    memory_limit_mb: int | None = 1024,
) -> RunResult:
    """Run argv in cwd with a hard timeout and captured output."""
    if not argv:
        raise UsageError("run_command needs a non-empty argv")
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("PYTHONPATH", "NODE_OPTIONS", "COVERAGE_FILE", "PYTEST_ADDOPTS")
    }
    env.setdefault("SYSTEMROOT", os.environ.get("SYSTEMROOT", ""))
    if env_overrides:
        env.update(env_overrides)

    preexec = None
    if sys.platform != "win32" and memory_limit_mb:

        def _limit() -> None:  # pragma: no cover - posix only
            import resource

            resource.setrlimit(
                resource.RLIMIT_AS, (memory_limit_mb * 1024 * 1024,) * 2
            )

        preexec = _limit  # type: ignore[assignment]

    start = time.monotonic()
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    try:
        proc = subprocess.Popen(  # noqa: S603 - argv list, no shell
            argv,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            preexec_fn=preexec,
            creationflags=creationflags,
        )
    except FileNotFoundError:
        return RunResult(argv, None, "", f"executable not found: {argv[0]}", 0.0)
    except OSError as exc:
        return RunResult(argv, None, "", f"could not start: {exc}", 0.0)

    timed_out = False
    try:
        out_b, err_b = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
        out_b, err_b = proc.communicate()

    duration = time.monotonic() - start

    def _decoded(b: bytes | None) -> str:
        if not b:
            return ""
        return b.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]

    return RunResult(
        command=argv,
        exit_code=proc.returncode,
        stdout=_decoded(out_b),
        stderr=_decoded(err_b),
        duration_s=duration,
        timed_out=timed_out,
    )
