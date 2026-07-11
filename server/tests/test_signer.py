"""Tests for signer.py — HMAC-SHA256 sign/verify."""

import time

import pytest

from server.signer import (
    SIG_PREFIX,
    TIMESTAMP_WINDOW_SECONDS,
    compute_signature,
    verify_signature,
)

SECRET = "test-secret-do-not-use-in-prod"


def test_compute_signature_format():
    sig = compute_signature(SECRET, 1700000000, '{"command_id":"x","nonce":"abcdefgh"}')
    assert sig.startswith(SIG_PREFIX)
    digest = sig[len(SIG_PREFIX):]
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_compute_signature_changes_with_body():
    a = compute_signature(SECRET, 100, "hello")
    b = compute_signature(SECRET, 100, "hellp")
    assert a != b


def test_compute_signature_changes_with_ts():
    a = compute_signature(SECRET, 100, "hello")
    b = compute_signature(SECRET, 101, "hello")
    assert a != b


def test_compute_signature_changes_with_secret():
    a = compute_signature("a", 100, "hello")
    b = compute_signature("b", 100, "hello")
    assert a != b


def test_verify_signature_ok():
    ts = int(time.time())
    body = '{"command_id":"x","nonce":"nonce-1234"}'
    sig = compute_signature(SECRET, ts, body)
    ok, reason = verify_signature(SECRET, str(ts), sig, body)
    assert ok is True
    assert reason == ""


def test_verify_signature_missing_timestamp():
    ok, reason = verify_signature(SECRET, None, "sha256=abc", "x")
    assert ok is False
    assert "X-Panel-Timestamp" in reason


def test_verify_signature_missing_signature():
    ok, reason = verify_signature(SECRET, "100", None, "x")
    assert ok is False
    assert "X-Panel-Signature" in reason


def test_verify_signature_bad_prefix():
    ts = int(time.time())
    ok, reason = verify_signature(SECRET, str(ts), "deadbeef", "x")
    assert ok is False
    assert "sha256=" in reason


def test_verify_signature_timestamp_skew():
    body = "{}"
    sig = compute_signature(SECRET, 100, body)
    ok, reason = verify_signature(SECRET, "100", sig, body, now=100 + TIMESTAMP_WINDOW_SECONDS + 1)
    assert ok is False
    assert "window" in reason


def test_verify_signature_mismatch():
    body = '{"command_id":"x","nonce":"abc"}'
    sig = compute_signature(SECRET, int(time.time()), body)
    tampered = body.replace("x", "y")
    ok, reason = verify_signature(SECRET, str(int(time.time())), sig, tampered)
    assert ok is False
    assert reason == "signature mismatch"


def test_verify_signature_constant_time():
    """If compare_digest is used, verification time should not depend on the
    length of the matching prefix. We don't measure perf here; we just check
    that two differently-mismatched signatures both fail (sanity)."""
    body = "x"
    good = compute_signature(SECRET, 100, body)
    # Flip the last hex char
    flipped = good[:-1] + ("0" if good[-1] != "0" else "1")
    ok1, _ = verify_signature(SECRET, "100", good, body, now=100)
    ok2, _ = verify_signature(SECRET, "100", flipped, body, now=100)
    assert ok1 is True
    assert ok2 is False


def test_compute_signature_rejects_empty_secret():
    with pytest.raises(ValueError):
        compute_signature("", 100, "x")


def test_compute_signature_rejects_non_string_body():
    with pytest.raises(ValueError):
        compute_signature("k", 100, 123)  # type: ignore[arg-type]