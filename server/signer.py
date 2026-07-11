"""HMAC-SHA256 request signing & verification.

The wire format is:
    sig_hex = HMAC-SHA256(secret, f"{timestamp}.{body_bytes.decode()}")

Signature comparison is constant-time.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Final

ALGORITHM: Final[str] = "sha256"
TIMESTAMP_WINDOW_SECONDS: Final[int] = 300  # ±5 minutes
HEADER_SIGNATURE: Final[str] = "X-Panel-Signature"
HEADER_TIMESTAMP: Final[str] = "X-Panel-Timestamp"
HEADER_NONCE: Final[str] = "X-Panel-Nonce"
SIG_PREFIX: Final[str] = "sha256="


def compute_signature(secret: str, timestamp: int, body: str) -> str:
    """Return the hex HMAC-SHA256 signature for (secret, ts, body).

    body must already be the canonical serialized form (we use the raw request
    body bytes re-decoded as utf-8).
    """
    if not isinstance(secret, str) or not secret:
        raise ValueError("secret must be a non-empty string")
    if not isinstance(body, str):
        raise ValueError("body must be a string")
    msg = f"{timestamp}.{body}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"{SIG_PREFIX}{digest}"


def verify_signature(
    secret: str,
    timestamp_header: str | None,
    signature_header: str | None,
    body: str,
    now: int | None = None,
) -> tuple[bool, str]:
    """Verify the signature and timestamp window.

    Returns (ok, reason). reason is empty on success.
    """
    if not timestamp_header:
        return False, "missing X-Panel-Timestamp"
    if not signature_header:
        return False, "missing X-Panel-Signature"
    try:
        ts = int(timestamp_header)
    except ValueError:
        return False, "X-Panel-Timestamp not an integer"
    current = now if now is not None else int(time.time())
    if abs(current - ts) > TIMESTAMP_WINDOW_SECONDS:
        return False, "timestamp outside ±300s window"
    if not signature_header.startswith(SIG_PREFIX):
        return False, "signature missing sha256= prefix"
    expected = compute_signature(secret, ts, body)
    # constant-time compare
    if not hmac.compare_digest(expected, signature_header):
        return False, "signature mismatch"
    return True, ""