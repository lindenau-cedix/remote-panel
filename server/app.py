"""FastAPI webhook receiver.

Endpoints:
    GET  /healthz   — liveness, no auth
    GET  /buttons   — public button list (no argv)
    POST /hook      — execute a whitelisted command, requires HMAC

The Hot-reload of the whitelist on SIGHUP is wired in main().
"""

from __future__ import annotations

import json
import logging
import signal
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import audit
from .config import Settings
from .executor import execute
from .ratelimit import NonceStore, RateLimitConfig, TokenBucket
from .signer import verify_signature
from .whitelist import Whitelist, WhitelistError, load_whitelist


logger = logging.getLogger("remote_panel")


class HookBody(BaseModel):
    command_id: str = Field(..., min_length=1, max_length=64)
    nonce: str = Field(..., min_length=8, max_length=128)


def _client_ip(request: Request) -> str:
    # Trust loopback / X-Forwarded-For only when behind a reverse proxy you control.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def make_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app. settings=None reads from env."""
    if settings is None:
        settings = Settings()  # type: ignore[call-arg]
    if not settings.secret or len(settings.secret) < 16:
        raise RuntimeError(
            "PANEL_SECRET must be set and at least 16 chars. "
            "Generate one with: openssl rand -hex 32"
        )

    audit_log = audit.AuditLog(settings.audit_path)
    audit.set_default(audit_log)
    nonce_store = NonceStore(ttl_seconds=settings.nonce_ttl_seconds)
    rate_limiter = TokenBucket(
        RateLimitConfig(
            capacity=settings.rate_capacity,
            refill_per_sec=settings.rate_refill_per_sec,
        )
    )
    whitelist: Whitelist = load_whitelist(settings.whitelist_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info(
            "remote-panel started: %d commands whitelisted", len(list(whitelist.ids()))
        )

        def _reload(*_):
            nonlocal whitelist
            try:
                whitelist = load_whitelist(settings.whitelist_path)
                logger.info("whitelist reloaded: %d commands", len(list(whitelist.ids())))
                audit.record({"event": "whitelist.reload", "ok": True, "count": len(list(whitelist.ids()))})
            except WhitelistError as exc:
                logger.error("whitelist reload failed: %s", exc)
                audit.record({"event": "whitelist.reload", "ok": False, "error": str(exc)})

        signal.signal(signal.SIGHUP, _reload)
        try:
            yield
        finally:
            audit_log.close()

    app = FastAPI(title="remote-panel", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/buttons")
    async def buttons():
        return {"buttons": whitelist.public_buttons()}

    @app.post("/hook")
    async def hook(
        request: Request,
        x_panel_signature: str | None = Header(default=None, alias="X-Panel-Signature"),
        x_panel_timestamp: str | None = Header(default=None, alias="X-Panel-Timestamp"),
        x_panel_nonce: str | None = Header(default=None, alias="X-Panel-Nonce"),
    ):
        ip = _client_ip(request)

        # Rate limit FIRST so we don't burn CPU verifying sigs for floods.
        if not rate_limiter.allow(ip):
            audit.record({"event": "rate_limited", "ip": ip})
            return JSONResponse(
                status_code=429,
                content={"ok": False, "error": "rate limit exceeded"},
            )

        raw_body = await request.body()
        try:
            parsed = json.loads(raw_body.decode("utf-8"))
            body = HookBody(**parsed)
        except (json.JSONDecodeError, ValueError) as exc:
            audit.record({"event": "bad_body", "ip": ip, "error": str(exc)})
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": f"bad request body: {exc}"},
            )

        # Nonce from header must match body.nonce — both must be present.
        if not x_panel_nonce or x_panel_nonce != body.nonce:
            audit.record({"event": "nonce_mismatch", "ip": ip, "command_id": body.command_id})
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": "X-Panel-Nonce missing or does not match body.nonce"},
            )

        if not nonce_store.check_and_record(body.nonce):
            audit.record({"event": "replay", "ip": ip, "command_id": body.command_id, "nonce": body.nonce})
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": "nonce replayed"},
            )

        ok, reason = verify_signature(
            secret=settings.secret,
            timestamp_header=x_panel_timestamp,
            signature_header=x_panel_signature,
            body=raw_body.decode("utf-8"),
        )
        if not ok:
            audit.record({"event": "auth_fail", "ip": ip, "command_id": body.command_id, "reason": reason})
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": reason},
            )

        # Whitelist check
        if body.command_id not in whitelist:
            audit.record({"event": "not_whitelisted", "ip": ip, "command_id": body.command_id})
            return JSONResponse(
                status_code=403,
                content={"ok": False, "error": f"command_id {body.command_id!r} not in whitelist"},
            )

        spec = whitelist.get(body.command_id)
        audit.record({"event": "exec.start", "ip": ip, "command_id": body.command_id, "argv0": spec.argv[0]})
        t0 = time.monotonic()
        result = execute(spec)
        elapsed = int((time.monotonic() - t0) * 1000)
        audit.record({
            "event": "exec.done",
            "ip": ip,
            "command_id": body.command_id,
            "exit_code": result.exit_code,
            "duration_ms": elapsed,
            "timed_out": result.timed_out,
        })

        status = 408 if result.timed_out else 200
        return JSONResponse(
            status_code=status,
            content={
                "ok": (result.exit_code == 0 and not result.timed_out),
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "duration_ms": elapsed,
                "command_id": body.command_id,
            },
        )

    return app


def _build_default_app() -> FastAPI:
    """Build the module-level `app` so `uvicorn server.app:app` works.

    Settings reads PANEL_SECRET from env at construction time. If it's not set,
    uvicorn won't be able to boot, which is the desired behavior.
    """
    try:
        return make_app(Settings())  # type: ignore[call-arg]
    except Exception:
        # PANEL_SECRET may be missing during test collection; return a stub.
        return None  # type: ignore[return-value]


app = _build_default_app()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    import uvicorn

    uvicorn.run(
        "server.app:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
        factory=False,
    )


if __name__ == "__main__":
    main()