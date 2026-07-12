"""Tests for whitelist.py."""

import json
from pathlib import Path

import pytest

from server.whitelist import (
    ALLOWED_BASENAMES,
    CommandSpec,
    SshTarget,
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


# ---- ssh block ----------------------------------------------------------


def _write(tmp_path: Path, entry: dict) -> Path:
    f = tmp_path / "wl.json"
    f.write_text(json.dumps({"commands": [entry]}))
    return f


def test_ssh_block_optional(tmp_path: Path):
    """No ssh block at all → ssh is None on the spec."""
    f = _write(tmp_path, {"id": "x", "name": "n", "description": "d",
                           "argv": ["/bin/true"]})
    wl = load_whitelist(f)
    spec = wl.get("x")
    assert spec.ssh is None


def test_ssh_block_null_is_ok(tmp_path: Path):
    """Explicit null ssh is the same as absent."""
    f = _write(tmp_path, {"id": "x", "name": "n", "description": "d",
                           "argv": ["/bin/true"], "ssh": None})
    wl = load_whitelist(f)
    assert wl.get("x").ssh is None


def test_ssh_block_valid(tmp_path: Path):
    """A complete ssh block parses into a SshTarget."""
    entry = {
        "id": "x", "name": "n", "description": "d",
        "argv": ["/usr/local/bin/sim24", "book"],
        "ssh": {
            "host": "localhost",
            "user": "root",
            "key_path": "/etc/panel/ssh/x.ed25519",
        },
    }
    f = _write(tmp_path, entry)
    wl = load_whitelist(f)
    spec = wl.get("x")
    assert spec.ssh == SshTarget(
        host="localhost", user="root",
        key_path="/etc/panel/ssh/x.ed25519",
    )


def test_ssh_block_required_keys(tmp_path: Path):
    """Missing any of host/user/key_path → WhitelistError."""
    base = {"id": "x", "name": "n", "description": "d",
            "argv": ["/bin/true"], "ssh": {
                "host": "localhost",
                "user": "root",
                "key_path": "/etc/panel/ssh/x.ed25519",
            }}
    for missing in ("host", "user", "key_path"):
        bad = {**base, "ssh": {k: v for k, v in base["ssh"].items() if k != missing}}
        f = _write(tmp_path, bad)
        with pytest.raises(WhitelistError, match=missing):
            load_whitelist(f)


def test_ssh_block_empty_value_rejected(tmp_path: Path):
    base = {"id": "x", "name": "n", "description": "d",
            "argv": ["/bin/true"], "ssh": {
                "host": "localhost",
                "user": "root",
                "key_path": "/etc/panel/ssh/x.ed25519",
            }}
    bad = {**base, "ssh": {**base["ssh"], "user": ""}}
    f = _write(tmp_path, bad)
    with pytest.raises(WhitelistError, match="user"):
        load_whitelist(f)


def test_ssh_block_key_path_must_be_absolute(tmp_path: Path):
    base = {"id": "x", "name": "n", "description": "d",
            "argv": ["/bin/true"], "ssh": {
                "host": "localhost",
                "user": "root",
                "key_path": "/etc/panel/ssh/x.ed25519",
            }}
    bad = {**base, "ssh": {**base["ssh"], "key_path": "relative/key"}}
    f = _write(tmp_path, bad)
    with pytest.raises(WhitelistError, match="absolute"):
        load_whitelist(f)


def test_ssh_block_bad_host_chars(tmp_path: Path):
    base = {"id": "x", "name": "n", "description": "d",
            "argv": ["/bin/true"], "ssh": {
                "host": "localhost",
                "user": "root",
                "key_path": "/etc/panel/ssh/x.ed25519",
            }}
    # Embedded space is the typical "shell injection" pattern.
    bad = {**base, "ssh": {**base["ssh"], "host": "evil host; rm -rf /"}}
    f = _write(tmp_path, bad)
    with pytest.raises(WhitelistError, match="host"):
        load_whitelist(f)


def test_ssh_block_must_be_object(tmp_path: Path):
    entry = {"id": "x", "name": "n", "description": "d",
             "argv": ["/bin/true"], "ssh": "localhost"}
    f = _write(tmp_path, entry)
    with pytest.raises(WhitelistError, match="object"):
        load_whitelist(f)


def test_ssh_block_round_trip(tmp_path: Path):
    """to_dict() preserves the ssh block so SIGHUP reload works."""
    entry = {
        "id": "x", "name": "n", "description": "d",
        "argv": ["/bin/true"],
        "ssh": {
            "host": "host.example.com",
            "user": "panel",
            "key_path": "/etc/panel/ssh/x.ed25519",
        },
    }
    f = _write(tmp_path, entry)
    wl = load_whitelist(f)
    spec = wl.get("x")
    out = spec.to_dict()
    assert out["ssh"] == entry["ssh"]

    # And re-loading the to_dict() output should round-trip.
    f2 = tmp_path / "wl2.json"
    f2.write_text(json.dumps({"commands": [out]}))
    wl2 = load_whitelist(f2)
    assert wl2.get("x").ssh == spec.ssh