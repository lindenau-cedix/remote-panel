"""Subprocess executor.

Runs a pre-validated argv list. NEVER uses shell=True, os.system, or string
exec. The argv list comes from the server-side whitelist, not the request body.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass

from .whitelist import CommandSpec


@dataclass(frozen=True)
class ExecutionResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    timed_out: bool


def execute(spec: CommandSpec, env_extra: dict[str, str] | None = None) -> ExecutionResult:
    """Execute the given command spec. No shell.

    Raises FileNotFoundError if argv[0] is not on disk (shouldn't happen for
    whitelisted entries, but it's a loud failure rather than silent).
    """
    env = os.environ.copy()
    env.update(spec.env)
    if env_extra:
        env.update(env_extra)

    start = time.monotonic()
    try:
        proc = subprocess.run(
            spec.argv,
            cwd=spec.cwd,
            env=env,
            capture_output=True,
            text=True,
            shell=False,  # explicit; default in modern Python
            check=False,
            timeout=spec.timeout_seconds,
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        return ExecutionResult(
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            exit_code=proc.returncode,
            duration_ms=duration_ms,
            timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        return ExecutionResult(
            stdout=(exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
            stderr=(exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or ""),
            exit_code=124,  # conventional timeout exit code
            duration_ms=duration_ms,
            timed_out=True,
        )