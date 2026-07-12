"""Subprocess executor.

Runs a pre-validated argv list. NEVER uses shell=True, os.system, or string
exec. The argv list comes from the server-side whitelist, not the request body.

Optional SSH-wrap (Plan B): if `spec.ssh` is set (per-command override), or
`Settings.ssh_*` is set (global default), the local argv is wrapped in
`ssh -i <key> -l <user> <host> -- <argv>`. The wrapping is constructed as a
list — no shell expansion happens on the panel side — so shell=False still
holds. The remote sshd enforces a separate authorization boundary via the
`command=` directive in its authorized_keys file.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass

from .whitelist import CommandSpec, SshTarget


# Default location of the SSH known_hosts file inside the container.
# Mounted read-only from the host (see deploy/docker/docker-compose.yml).
KNOWN_HOSTS_PATH = "/etc/panel/ssh/known_hosts"

# How long ssh is allowed to spend just establishing the connection
# before we give up. The spec's timeout_seconds still wraps the whole
# subprocess; this is only the per-connect cap.
CONNECT_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class ExecutionResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    timed_out: bool


def _wrap_for_ssh(spec: CommandSpec, target: SshTarget) -> list[str]:
    """Build the argv list passed to subprocess.run when SSH is in use.

    Returns a list of strings suitable for `subprocess.run(argv, shell=False)`.
    The remote shell (the user's login shell on the host) parses the
    tail of the list: KEY=VAL pairs, optional `cd <cwd> &&`, then the
    original argv.

    Defense-in-depth: the whitelist validator already enforces argv[0]
    is absolute (or sudo/systemctl), cwd is absolute, env keys are
    strings, and ssh.host matches a permissive regex. The remote side
    still validates argv via the SSH `command=` pin in authorized_keys
    — neither layer alone is sufficient.
    """
    remote_argv: list[str] = []

    # Forward spec.env as KEY=VAL prefix. We do NOT use `ssh -o SendEnv`
    # because that requires matching AcceptEnv on the host sshd config,
    # which we don't want to depend on.
    for k, v in spec.env.items():
        remote_argv.append(f"{k}={v}")

    # Forward spec.cwd by prefixing `cd <cwd> &&`. The remote shell
    # parses this; if cwd is bad on the host side, sshd will return
    # 127-style "no such file" exit and the user sees it in stderr.
    if spec.cwd is not None:
        remote_argv.extend(["cd", spec.cwd, "&&"])

    # The actual command (already validated as absolute-path argv[0]).
    remote_argv.extend(spec.argv)

    return [
        "ssh",
        "-i", target.key_path,
        "-o", "BatchMode=yes",                    # never prompt
        "-o", "StrictHostKeyChecking=yes",        # require known host key
        "-o", f"UserKnownHostsFile={KNOWN_HOSTS_PATH}",
        "-o", "LogLevel=ERROR",                    # keep stderr clean
        "-o", f"ConnectTimeout={CONNECT_TIMEOUT_SECONDS}",
        "-l", target.user,
        target.host,
        "--",                                      # end of ssh options
        *remote_argv,
    ]


def execute(
    spec: CommandSpec,
    env_extra: dict[str, str] | None = None,
    ssh_target: SshTarget | None = None,
) -> ExecutionResult:
    """Execute the given command spec. No shell on the panel side.

    When `ssh_target` is provided, argv is wrapped via `_wrap_for_ssh`.
    Callers (server.app) pass `Settings.ssh_*` merged with any
    per-command override; passing `None` runs the command locally as
    before.

    Raises FileNotFoundError if argv[0] (or `ssh` itself, when wrapping)
    is not on disk — loud failure rather than silent.
    """
    if ssh_target is not None:
        argv = _wrap_for_ssh(spec, ssh_target)
        cwd = None  # remote cwd is set via the wrapped shell prefix
    else:
        argv = spec.argv
        cwd = spec.cwd

    env = os.environ.copy()
    env.update(spec.env)
    if env_extra:
        env.update(env_extra)

    start = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
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