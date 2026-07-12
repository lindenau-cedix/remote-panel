"""Whitelist loader and validator.

The whitelist is a JSON file mapping `command_id` to argv list. The client only
sends `command_id`; the server substitutes the argv. This means we never
accept an arbitrary command from the wire — only the pre-vetted ids.

Validation rules:
- ids unique, kebab-case, non-empty
- argv non-empty, every element a non-empty string
- argv[0] must be an absolute path OR a name in ALLOWED_BASENAMES
- cwd, if present, must be an absolute path
- env, if present, keys+values must be strings
- timeout_seconds, if present, must be > 0
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

# These are the only base names (argv[0]) allowed without an absolute path.
# Anything else must be an absolute path.
ALLOWED_BASENAMES: frozenset[str] = frozenset({"sudo", "systemctl"})

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class WhitelistError(ValueError):
    """Raised when the whitelist file is invalid or a command is not whitelisted."""


@dataclass(frozen=True)
class SshTarget:
    """Per-command SSH target. Overrides global Settings SSH fields.

    The executor wraps the argv in `ssh -i key -l user host -- <argv>`
    when this is set. Field semantics match the `ssh` block in the
    whitelist JSON.
    """
    host: str
    user: str
    key_path: str  # absolute path to the private key inside the container


class CommandSpec:
    __slots__ = ("id", "name", "description", "argv", "cwd", "env", "timeout_seconds", "ssh")

    def __init__(
        self,
        id: str,
        name: str,
        description: str,
        argv: list[str],
        cwd: Optional[str],
        env: dict[str, str],
        timeout_seconds: int,
        ssh: Optional[SshTarget] = None,
    ) -> None:
        self.id = id
        self.name = name
        self.description = description
        self.argv = argv
        self.cwd = cwd
        self.env = env
        self.timeout_seconds = timeout_seconds
        self.ssh = ssh

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "env": dict(self.env),
            "timeout_seconds": self.timeout_seconds,
        }
        if self.ssh is not None:
            d["ssh"] = {
                "host": self.ssh.host,
                "user": self.ssh.user,
                "key_path": self.ssh.key_path,
            }
        return d

    def public_dict(self) -> dict:
        """What /buttons returns — never the argv."""
        return {"id": self.id, "name": self.name, "description": self.description}


class Whitelist:
    def __init__(self, commands: dict[str, CommandSpec]) -> None:
        self._commands = commands

    def __contains__(self, command_id: str) -> bool:
        return command_id in self._commands

    def get(self, command_id: str) -> CommandSpec:
        try:
            return self._commands[command_id]
        except KeyError:
            raise WhitelistError(f"command_id {command_id!r} not in whitelist") from None

    def public_buttons(self) -> list[dict]:
        return [c.public_dict() for c in self._commands.values()]

    def ids(self) -> Iterable[str]:
        return self._commands.keys()


def _validate_argv0(argv0: str) -> None:
    """argv[0] must be absolute or in ALLOWED_BASENAMES."""
    if os.path.isabs(argv0):
        return
    if argv0 in ALLOWED_BASENAMES:
        return
    raise WhitelistError(
        f"argv[0]={argv0!r} must be an absolute path or one of "
        f"{sorted(ALLOWED_BASENAMES)}"
    )


# Permissive host pattern. Covers hostnames, IPv4, IPv6 in brackets,
# and trailing :port. Does NOT cover ssh-style user@host or any
# quoting — those are not allowed: user goes in `ssh.user` and host
# is just the host.
_SSH_HOST_RE = re.compile(r"^\[?[A-Za-z0-9.\-:]+\]?$")


def _validate_ssh(raw, cid: str) -> Optional[SshTarget]:
    """Validate the optional `ssh` block in a whitelist entry.

    Returns None if absent or null. Raises WhitelistError on any
    structural problem so a bad entry fails the whole whitelist load
    (same loud-failure behavior as the rest of the validator).
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise WhitelistError(f"{cid}: 'ssh' must be an object or null")
    for fld in ("host", "user", "key_path"):
        v = raw.get(fld)
        if not isinstance(v, str) or not v:
            raise WhitelistError(
                f"{cid}: ssh.{fld} must be a non-empty string"
            )
    key_path = raw["key_path"]
    if not os.path.isabs(key_path):
        raise WhitelistError(f"{cid}: ssh.key_path must be an absolute path")
    if not _SSH_HOST_RE.match(raw["host"]):
        raise WhitelistError(
            f"{cid}: ssh.host={raw['host']!r} has unexpected characters"
        )
    return SshTarget(
        host=raw["host"],
        user=raw["user"],
        key_path=key_path,
    )


def _validate_one(raw: dict) -> CommandSpec:
    if not isinstance(raw, dict):
        raise WhitelistError(f"command entry must be an object, got {type(raw).__name__}")
    cid = raw.get("id")
    if not isinstance(cid, str) or not ID_PATTERN.match(cid):
        raise WhitelistError(f"id {cid!r} invalid: must match {ID_PATTERN.pattern}")
    if raw.get("name") is None or not isinstance(raw.get("name"), str):
        raise WhitelistError(f"{cid}: missing or invalid 'name'")
    if raw.get("description") is None or not isinstance(raw.get("description"), str):
        raise WhitelistError(f"{cid}: missing or invalid 'description'")
    argv = raw.get("argv")
    if not isinstance(argv, list) or not argv:
        raise WhitelistError(f"{cid}: 'argv' must be a non-empty list")
    if not all(isinstance(a, str) and a for a in argv):
        raise WhitelistError(f"{cid}: every argv element must be a non-empty string")
    _validate_argv0(argv[0])
    cwd = raw.get("cwd")
    if cwd is not None and (not isinstance(cwd, str) or not os.path.isabs(cwd)):
        raise WhitelistError(f"{cid}: 'cwd' must be an absolute path or null")
    env = raw.get("env", {})
    if not isinstance(env, dict):
        raise WhitelistError(f"{cid}: 'env' must be an object")
    for k, v in env.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise WhitelistError(f"{cid}: env keys and values must be strings")
    timeout = raw.get("timeout_seconds", 30)
    if not isinstance(timeout, int) or timeout <= 0:
        raise WhitelistError(f"{cid}: 'timeout_seconds' must be a positive integer")
    ssh = _validate_ssh(raw.get("ssh"), cid)
    return CommandSpec(
        id=cid,
        name=raw["name"],
        description=raw["description"],
        argv=list(argv),
        cwd=cwd,
        env=dict(env),
        timeout_seconds=timeout,
        ssh=ssh,
    )


def load_whitelist(path: str | Path) -> Whitelist:
    p = Path(path)
    if not p.is_file():
        raise WhitelistError(f"whitelist file not found: {p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WhitelistError(f"invalid JSON in {p}: {exc}") from exc
    if not isinstance(raw, dict) or "commands" not in raw:
        raise WhitelistError("whitelist must be a JSON object with 'commands'")
    cmds_raw = raw["commands"]
    if not isinstance(cmds_raw, list):
        raise WhitelistError("'commands' must be a list")
    seen: dict[str, CommandSpec] = {}
    for entry in cmds_raw:
        spec = _validate_one(entry)
        if spec.id in seen:
            raise WhitelistError(f"duplicate command id: {spec.id}")
        seen[spec.id] = spec
    if not seen:
        raise WhitelistError("whitelist must define at least one command")
    return Whitelist(seen)