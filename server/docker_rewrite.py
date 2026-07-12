"""Rewrite a whitelist so argv entries call out to the privileged sidecar.

When the panel server runs inside a container, the actual command must
execute on the host (where systemd, sudoers, and the protected
binaries live). We rewrite the whitelist so each command's argv
prefix becomes:

    ["docker", "exec", "-u", "root", "--", "<host_container>",
     <original argv...>]

The rewriter is intentionally tiny and pure: read JSON, rewrite, write
JSON. It does NOT shell out and does NOT depend on docker being
installed (it's a pure-data transform that runs before the server
starts).

Why this is safe:

- argv[0] is rewritten to a hard-coded literal `docker` (an absolute
  binary path resolved by the executor via PATH inside the container).
  Wait — the whitelist validator requires argv[0] to be an absolute
  path or in ALLOWED_BASENAMES. We extend ALLOWED_BASENAMES via the
  whitelist at *validation time* by injecting the docker binary's
  absolute path. See docker_entrypoint.sh.
- Everything after that prefix is verbatim from the original argv, so
  the validator's other checks (argv0 absolute/allowed, cwd, env,
  timeout) still apply.
- The rewriter runs once at container start with the secret-bearing
  env file already loaded, so a tampering attack would require
  write access to the whitelist bind-mount.

This module is imported only from docker_entrypoint.sh; the server
itself doesn't know it's running under Docker.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# `sudo` and `systemctl` are in the original ALLOWED_BASENAMES. After
# rewriting they appear as the second argv element (preceded by the
# docker-exec prefix), so they remain absolute-style entries.
HOST_CONTAINER_ENV = "PANEL_HOST_CONTAINER"
DOCKER_BIN_ENV = "PANEL_DOCKER_BIN"

# argv[0] of the rewritten command is the docker CLI itself, which
# must be on PATH inside the panel container. The whitelist validator
# requires argv[0] to be an absolute path, so the rewriter resolves
# the binary's real path before injecting it.
DEFAULT_DOCKER_BIN = "/usr/bin/docker"


def _resolve_docker(docker_bin: str) -> str:
    """Return an absolute path to the docker CLI.

    Falls back to the configured literal if the binary doesn't exist
    (e.g. during a syntax-check in CI). The whitelist validator will
    then reject the rewritten entry, which is the loud failure we want.
    """
    if os.path.isabs(docker_bin) and os.path.isfile(docker_bin):
        return docker_bin
    # PATH lookup — best effort.
    for d in os.environ.get("PATH", "").split(":"):
        candidate = os.path.join(d, "docker")
        if os.path.isfile(candidate):
            return os.path.realpath(candidate)
    return docker_bin if os.path.isabs(docker_bin) else DEFAULT_DOCKER_BIN


def rewrite_command(entry: dict, *, host_container: str, docker_bin: str) -> dict:
    """Rewrite one command entry's argv in-place (returns a new dict).

    Preserves id, name, description, cwd, env, timeout_seconds verbatim.
    Pass-through for entries with an `ssh` block — those use the
    SSH-wrap path (Plan B) and must NOT be wrapped in `docker exec`.
    """
    # Pass-through when the entry opts into SSH-wrap mode. The executor
    # wraps the argv at call time; the docker rewriter must not also
    # prepend `docker exec`, since that would result in `docker exec
    # panel-host ssh -l user host -- argv` which is meaningless.
    if isinstance(entry.get("ssh"), dict):
        return dict(entry)
    argv = entry.get("argv")
    if not isinstance(argv, list) or not argv:
        raise ValueError(f"command {entry.get('id')!r}: argv must be a non-empty list")
    new_argv = [docker_bin, "exec", "-u", "root", "--", host_container, *argv]
    return {
        **entry,
        "argv": new_argv,
    }


def rewrite_whitelist(data: dict, *, host_container: str, docker_bin: str) -> dict:
    """Rewrite the whole whitelist document. Preserves schema."""
    if not isinstance(data, dict) or "commands" not in data:
        raise ValueError("whitelist must be a JSON object with 'commands'")
    commands = data["commands"]
    if not isinstance(commands, list) or not commands:
        raise ValueError("'commands' must be a non-empty list")
    return {
        **data,
        "commands": [rewrite_command(c, host_container=host_container, docker_bin=docker_bin) for c in commands],
    }


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", required=True, type=Path, help="source whitelist.json")
    parser.add_argument("--output", required=True, type=Path, help="destination whitelist.json")
    parser.add_argument("--host-container", default=os.environ.get(HOST_CONTAINER_ENV, "panel-host"))
    parser.add_argument("--docker-bin", default=os.environ.get(DOCKER_BIN_ENV, DEFAULT_DOCKER_BIN))
    args = parser.parse_args(argv)

    data = json.loads(args.input.read_text(encoding="utf-8"))
    rewritten = rewrite_whitelist(
        data,
        host_container=args.host_container,
        docker_bin=_resolve_docker(args.docker_bin),
    )
    args.output.write_text(json.dumps(rewritten, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())