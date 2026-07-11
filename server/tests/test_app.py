"""End-to-end tests for the FastAPI app.

Uses httpx.AsyncClient with the FastAPI app directly (no network socket).
"""

import json
import os
import time
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Set PANEL_SECRET BEFORE importing the app.
os.environ.setdefault("PANEL_SECRET", "test-secret-for-pytest-1234567890")

from server import audit  # noqa: E402
from server.app import make_app  # noqa: E402
from server.config import Settings  # noqa: E402
from server.signer import compute_signature  # noqa: E402

# Use an isolated temp whitelist for tests so we can add a harmless command.
GOOD_CMD = {
    "commands": [
        {
            "id": "echo-hello",
            "name": "Echo Hello",
            "description": "Print hello to stdout",
            "argv": ["/bin/echo", "hello-from-panel"],
            "cwd": None,
            "env": {},
            "timeout_seconds": 5,
        },
        {
            "id": "fail-on-purpose",
            "name": "Fail",
            "description": "Exits with code 9",
            "argv": ["/bin/sh", "-c", "echo oops 1>&2; exit 9"],
            "cwd": None,
            "env": {},
            "timeout_seconds": 5,
        },
    ]
}


@pytest_asyncio.fixture
async def client(tmp_path: Path, monkeypatch):
    wl = tmp_path / "wl.json"
    wl.write_text(json.dumps(GOOD_CMD))
    audit_p = tmp_path / "audit.jsonl"
    settings = Settings(
        secret="test-secret-for-pytest-1234567890",
        whitelist_path=wl,
        audit_path=audit_p,
    )
    application = make_app(settings)
    # The make_app call already wired audit.AuditLog(settings.audit_path) as the
    # default; we keep it that way so audit events get written to tmp_path.
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, application, settings, audit_p
    # Cleanup: drop the default singleton between tests so file handles close.
    audit.set_default(None)


def _sign(secret: str, body: str, ts: int | None = None) -> tuple[str, str, str]:
    """Sign a body and return (signature, timestamp_str, nonce).

    Uses the same nonce string the body says it has, so header/body agree.
    """
    ts = ts if ts is not None else int(time.time())
    parsed = json.loads(body)
    nonce = parsed["nonce"]
    sig = compute_signature(secret, ts, body)
    return sig, str(ts), nonce


@pytest.mark.asyncio
async def test_healthz(client):
    c, _, _, _ = client
    r = await c.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


@pytest.mark.asyncio
async def test_buttons_omits_argv(client):
    c, _, _, _ = client
    r = await c.get("/buttons")
    assert r.status_code == 200
    buttons = r.json()["buttons"]
    ids = {b["id"] for b in buttons}
    assert ids == {"echo-hello", "fail-on-purpose"}
    for b in buttons:
        assert "argv" not in b


@pytest.mark.asyncio
async def test_hook_success(client):
    c, _, settings, _ = client
    body = json.dumps({"command_id": "echo-hello", "nonce": "n-success-1234"})
    sig, ts, nonce = _sign(settings.secret, body)
    r = await c.post(
        "/hook",
        content=body,
        headers={
            "X-Panel-Signature": sig,
            "X-Panel-Timestamp": ts,
            "X-Panel-Nonce": nonce,
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    assert j["exit_code"] == 0
    assert "hello-from-panel" in j["stdout"]
    assert j["command_id"] == "echo-hello"
    assert j["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_hook_bad_signature_returns_400(client):
    c, _, _, _ = client
    body = json.dumps({"command_id": "echo-hello", "nonce": "n-bad-1234"})
    r = await c.post(
        "/hook",
        content=body,
        headers={
            "X-Panel-Signature": "sha256=" + "0" * 64,
            "X-Panel-Timestamp": str(int(time.time())),
            "X-Panel-Nonce": "n-bad-1234",
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 400
    assert "signature" in r.json()["error"].lower() or "mismatch" in r.json()["error"].lower()


@pytest.mark.asyncio
async def test_hook_missing_headers_returns_400(client):
    c, _, _, _ = client
    body = json.dumps({"command_id": "echo-hello", "nonce": "n-missing-1234"})
    r = await c.post("/hook", content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_hook_non_whitelisted_returns_403(client):
    c, _, settings, _ = client
    body = json.dumps({"command_id": "rm-rf", "nonce": "n-notwhitelisted-99"})
    sig, ts, nonce = _sign(settings.secret, body)
    r = await c.post(
        "/hook",
        content=body,
        headers={
            "X-Panel-Signature": sig,
            "X-Panel-Timestamp": ts,
            "X-Panel-Nonce": nonce,
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 403
    assert "whitelist" in r.json()["error"].lower()


@pytest.mark.asyncio
async def test_hook_replay_blocked(client):
    c, _, settings, _ = client
    body = json.dumps({"command_id": "echo-hello", "nonce": "n-replay-12345"})
    sig, ts, nonce = _sign(settings.secret, body)
    headers = {
        "X-Panel-Signature": sig,
        "X-Panel-Timestamp": ts,
        "X-Panel-Nonce": nonce,
        "Content-Type": "application/json",
    }
    r1 = await c.post("/hook", content=body, headers=headers)
    assert r1.status_code == 200
    # Same nonce again — must be rejected.
    r2 = await c.post("/hook", content=body, headers=headers)
    assert r2.status_code == 400
    assert "replayed" in r2.json()["error"].lower() or "nonce" in r2.json()["error"].lower()


@pytest.mark.asyncio
async def test_hook_timestamp_window(client):
    c, _, settings, _ = client
    body = json.dumps({"command_id": "echo-hello", "nonce": "n-old-1234567"})
    # Sign with an old timestamp.
    old_ts = int(time.time()) - 400  # > 300s window
    sig, ts, nonce = _sign(settings.secret, body, ts=old_ts)
    r = await c.post(
        "/hook",
        content=body,
        headers={
            "X-Panel-Signature": sig,
            "X-Panel-Timestamp": ts,
            "X-Panel-Nonce": nonce,
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 400
    assert "window" in r.json()["error"].lower() or "timestamp" in r.json()["error"].lower()


@pytest.mark.asyncio
async def test_hook_nonce_header_mismatch(client):
    c, _, settings, _ = client
    body = json.dumps({"command_id": "echo-hello", "nonce": "n-real-123456"})
    sig, ts, _ = _sign(settings.secret, body)
    r = await c.post(
        "/hook",
        content=body,
        headers={
            "X-Panel-Signature": sig,
            "X-Panel-Timestamp": ts,
            "X-Panel-Nonce": "different-nonce-header",
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_hook_exit_code_propagates(client):
    c, _, settings, _ = client
    body = json.dumps({"command_id": "fail-on-purpose", "nonce": "n-fail-1234567"})
    sig, ts, nonce = _sign(settings.secret, body)
    r = await c.post(
        "/hook",
        content=body,
        headers={
            "X-Panel-Signature": sig,
            "X-Panel-Timestamp": ts,
            "X-Panel-Nonce": nonce,
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 200  # request succeeded; command itself failed
    j = r.json()
    assert j["ok"] is False
    assert j["exit_code"] == 9
    assert "oops" in j["stderr"]


@pytest.mark.asyncio
async def test_rate_limit_kicks_in(client):
    """Hit /hook many times with distinct nonces; eventually get 429."""
    c, _, settings, _ = client
    # Default rate capacity is 30. Hit it hard.
    last_status = None
    saw_429 = False
    for i in range(40):
        body = json.dumps({"command_id": "echo-hello", "nonce": f"n-rl-{i:04d}-xx"})
        sig, ts, nonce = _sign(settings.secret, body)
        r = await c.post(
            "/hook",
            content=body,
            headers={
                "X-Panel-Signature": sig,
                "X-Panel-Timestamp": ts,
                "X-Panel-Nonce": nonce,
                "Content-Type": "application/json",
            },
        )
        last_status = r.status_code
        if r.status_code == 429:
            saw_429 = True
            break
    assert saw_429, f"never got 429 in 40 attempts (last={last_status})"


@pytest.mark.asyncio
async def test_audit_log_written(client):
    c, _, settings, audit_p = client
    body = json.dumps({"command_id": "echo-hello", "nonce": "n-audit-1234567"})
    sig, ts, nonce = _sign(settings.secret, body)
    await c.post(
        "/hook",
        content=body,
        headers={
            "X-Panel-Signature": sig,
            "X-Panel-Timestamp": ts,
            "X-Panel-Nonce": nonce,
            "Content-Type": "application/json",
        },
    )
    # The app's AuditLog was set as the default at make_app() time and writes
    # are line-buffered. Re-reading the file should see exec.done.
    lines = audit_p.read_text(encoding="utf-8").strip().splitlines()
    assert any("exec.done" in line for line in lines), lines