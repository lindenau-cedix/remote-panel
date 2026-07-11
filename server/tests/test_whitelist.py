"""Tests for whitelist.py."""

import json
from pathlib import Path

import pytest

from server.whitelist import (
    ALLOWED_BASENAMES,
    CommandSpec,
    Whitelist,
    WhitelistError,
    load_whitelist,
)


VALID = {
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


def test_load_valid(tmp_path: Path):
    f = tmp_path / "wl.json"
    f.write_text(json.dumps(VALID))
    wl = load_whitelist(f)
    assert "restart-nginx" in wl
    assert "deploy-site" in wl
    spec = wl.get("deploy-site")
    assert spec.argv == ["/opt/panel/bin/deploy.sh"]
    assert spec.cwd == "/opt/panel"
    assert spec.env == {"DEPLOY_ENV": "production"}


def test_load_missing_file(tmp_path: Path):
    with pytest.raises(WhitelistError):
        load_whitelist(tmp_path / "nope.json")


def test_load_invalid_json(tmp_path: Path):
    f = tmp_path / "wl.json"
    f.write_text("not json")
    with pytest.raises(WhitelistError):
        load_whitelist(f)


def test_load_no_commands(tmp_path: Path):
    f = tmp_path / "wl.json"
    f.write_text(json.dumps({"commands": []}))
    with pytest.raises(WhitelistError, match="at least one"):
        load_whitelist(f)


def test_duplicate_ids(tmp_path: Path):
    data = {
        "commands": [
            {"id": "x", "name": "X", "description": "x", "argv": ["/bin/true"]},
            {"id": "x", "name": "Y", "description": "y", "argv": ["/bin/true"]},
        ]
    }
    f = tmp_path / "wl.json"
    f.write_text(json.dumps(data))
    with pytest.raises(WhitelistError, match="duplicate"):
        load_whitelist(f)


def test_id_validation(tmp_path: Path):
    bad_ids = ["X", "-leading-dash", "has space", "", "a" * 65]
    for bad in bad_ids:
        data = {"commands": [{"id": bad, "name": "n", "description": "d", "argv": ["/bin/true"]}]}
        f = tmp_path / "wl.json"
        f.write_text(json.dumps(data))
        with pytest.raises(WhitelistError):
            load_whitelist(f)


def test_argv_must_be_nonempty(tmp_path: Path):
    data = {"commands": [{"id": "x", "name": "n", "description": "d", "argv": []}]}
    f = tmp_path / "wl.json"
    f.write_text(json.dumps(data))
    with pytest.raises(WhitelistError, match="argv"):
        load_whitelist(f)


def test_argv0_must_be_absolute_or_allowed(tmp_path: Path):
    data = {"commands": [{"id": "x", "name": "n", "description": "d", "argv": ["curl", "-s", "http://evil"]}]}
    f = tmp_path / "wl.json"
    f.write_text(json.dumps(data))
    with pytest.raises(WhitelistError, match="absolute path"):
        load_whitelist(f)


def test_argv0_allowed_basenames(tmp_path: Path):
    data = {"commands": [{"id": "x", "name": "n", "description": "d", "argv": ["sudo", "-n", "whoami"]}]}
    f = tmp_path / "wl.json"
    f.write_text(json.dumps(data))
    wl = load_whitelist(f)
    assert "x" in wl


def test_cwd_must_be_absolute(tmp_path: Path):
    data = {
        "commands": [
            {"id": "x", "name": "n", "description": "d", "argv": ["/bin/true"], "cwd": "relative/path"}
        ]
    }
    f = tmp_path / "wl.json"
    f.write_text(json.dumps(data))
    with pytest.raises(WhitelistError, match="cwd"):
        load_whitelist(f)


def test_env_must_be_strings(tmp_path: Path):
    data = {
        "commands": [
            {"id": "x", "name": "n", "description": "d", "argv": ["/bin/true"], "env": {"k": 1}}
        ]
    }
    f = tmp_path / "wl.json"
    f.write_text(json.dumps(data))
    with pytest.raises(WhitelistError, match="env"):
        load_whitelist(f)


def test_timeout_must_be_positive(tmp_path: Path):
    data = {"commands": [{"id": "x", "name": "n", "description": "d", "argv": ["/bin/true"], "timeout_seconds": 0}]}
    f = tmp_path / "wl.json"
    f.write_text(json.dumps(data))
    with pytest.raises(WhitelistError, match="timeout_seconds"):
        load_whitelist(f)


def test_get_unknown_id_raises():
    wl = Whitelist({})
    with pytest.raises(WhitelistError, match="not in whitelist"):
        wl.get("nope")


def test_public_buttons_omits_argv(tmp_path: Path):
    f = tmp_path / "wl.json"
    f.write_text(json.dumps(VALID))
    wl = load_whitelist(f)
    buttons = wl.public_buttons()
    assert len(buttons) == 2
    for b in buttons:
        assert set(b.keys()) == {"id", "name", "description"}
        assert "argv" not in b