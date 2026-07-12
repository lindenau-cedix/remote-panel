"""Tests for the docker argv rewriter.

These tests don't require Docker to be installed — the rewriter is a
pure-data transform. They confirm:

- All commands are rewritten, none dropped or duplicated.
- argv[0] becomes an absolute docker binary path (so the whitelist
  validator accepts the rewritten entry).
- The validator accepts the rewritten output end-to-end.
- cwd, env, timeout_seconds, id, name, description are preserved.
- The original entry's argv is preserved verbatim after the docker-exec
  prefix (no element dropped, no element added).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.config import Settings
from server.docker_rewrite import (
    DEFAULT_DOCKER_BIN,
    rewrite_command,
    rewrite_whitelist,
)
from server.whitelist import load_whitelist


@pytest.fixture
def sample() -> dict:
    return {
        "commands": [
            {
                "id": "restart-nginx",
                "name": "Restart Nginx",
                "description": "Reload Nginx",
                "argv": ["sudo", "-n", "systemctl", "restart", "nginx"],
                "cwd": None,
                "env": {},
                "timeout_seconds": 10,
            },
            {
                "id": "deploy-site",
                "name": "Deploy Site",
                "description": "Pull latest",
                "argv": ["/opt/panel/bin/deploy.sh"],
                "cwd": "/opt/panel",
                "env": {"DEPLOY_ENV": "production"},
                "timeout_seconds": 60,
            },
        ]
    }


def test_rewrite_command_preserves_metadata(sample):
    original = sample["commands"][0]
    rewritten = rewrite_command(original, host_container="panel-host", docker_bin="/usr/bin/docker")
    assert rewritten["id"] == original["id"]
    assert rewritten["name"] == original["name"]
    assert rewritten["description"] == original["description"]
    assert rewritten["cwd"] == original["cwd"]
    assert rewritten["env"] == original["env"]
    assert rewritten["timeout_seconds"] == original["timeout_seconds"]


def test_rewrite_command_prepends_docker_exec(sample):
    rewritten = rewrite_command(sample["commands"][0], host_container="panel-host", docker_bin="/usr/bin/docker")
    expected_prefix = ["/usr/bin/docker", "exec", "-u", "root", "--", "panel-host"]
    assert rewritten["argv"][: len(expected_prefix)] == expected_prefix
    # The original argv follows verbatim.
    assert rewritten["argv"][len(expected_prefix):] == sample["commands"][0]["argv"]


def test_rewrite_command_preserves_absolute_argv0(sample):
    rewritten = rewrite_command(sample["commands"][1], host_container="panel-host", docker_bin="/usr/bin/docker")
    # Original argv[0] was an absolute path; it's now argv[6] (after the prefix).
    assert rewritten["argv"][6] == "/opt/panel/bin/deploy.sh"


def test_rewrite_whitelist_count_and_order(sample):
    out = rewrite_whitelist(sample, host_container="panel-host", docker_bin="/usr/bin/docker")
    assert len(out["commands"]) == len(sample["commands"])
    assert [c["id"] for c in out["commands"]] == [c["id"] for c in sample["commands"]]


def test_rewrite_whitelist_validates(sample, tmp_path: Path):
    out = rewrite_whitelist(sample, host_container="panel-host", docker_bin="/usr/bin/docker")
    target = tmp_path / "wl.json"
    target.write_text(json.dumps(out))

    settings = Settings(secret="x" * 32, whitelist_path=target)
    wl = load_whitelist(settings.whitelist_path)
    assert set(wl.ids()) == {"restart-nginx", "deploy-site"}


def test_rewrite_whitelist_rejects_malformed():
    with pytest.raises(ValueError):
        rewrite_whitelist({"commands": []}, host_container="x", docker_bin="/usr/bin/docker")
    with pytest.raises(ValueError):
        rewrite_whitelist({"oops": []}, host_container="x", docker_bin="/usr/bin/docker")


def test_rewrite_command_rejects_empty_argv():
    with pytest.raises(ValueError):
        rewrite_command({"id": "x", "argv": []}, host_container="x", docker_bin="/usr/bin/docker")


def test_rewrite_round_trip_through_validator(sample, tmp_path: Path):
    """End-to-end: rewrite then load through the production validator."""
    out = rewrite_whitelist(sample, host_container="panel-host", docker_bin="/usr/bin/docker")
    target = tmp_path / "wl.json"
    target.write_text(json.dumps(out))
    settings = Settings(secret="x" * 32, whitelist_path=target)
    wl = load_whitelist(settings.whitelist_path)
    spec = wl.get("restart-nginx")
    assert spec.argv[:6] == ["/usr/bin/docker", "exec", "-u", "root", "--", "panel-host"]
    assert spec.argv[6:] == ["sudo", "-n", "systemctl", "restart", "nginx"]


def test_default_docker_bin_is_absolute():
    # The whitelist validator rejects non-absolute argv[0] (unless in
    # ALLOWED_BASENAMES). The default must therefore be absolute.
    assert DEFAULT_DOCKER_BIN.startswith("/")