"""Tests for ratelimit.py — token bucket and nonce store."""

import time

from server.ratelimit import NonceStore, RateLimitConfig, TokenBucket


def test_token_bucket_allows_until_empty():
    cfg = RateLimitConfig(capacity=3, refill_per_sec=0.0)
    tb = TokenBucket(cfg)
    assert tb.allow("a") is True
    assert tb.allow("a") is True
    assert tb.allow("a") is True
    assert tb.allow("a") is False


def test_token_bucket_per_key():
    cfg = RateLimitConfig(capacity=1, refill_per_sec=0.0)
    tb = TokenBucket(cfg)
    assert tb.allow("a") is True
    assert tb.allow("a") is False
    assert tb.allow("b") is True


def test_token_bucket_refills():
    cfg = RateLimitConfig(capacity=1, refill_per_sec=10.0)  # 10/sec
    tb = TokenBucket(cfg)
    assert tb.allow("a", now=0.0) is True
    assert tb.allow("a", now=0.0) is False
    # 0.2s later, 2 tokens refilled -> capped at capacity 1
    assert tb.allow("a", now=0.2) is True


def test_nonce_store_rejects_duplicates():
    ns = NonceStore(ttl_seconds=60, max_entries=100)
    assert ns.check_and_record("abc") is True
    assert ns.check_and_record("abc") is False
    assert ns.check_and_record("def") is True


def test_nonce_store_ttl():
    ns = NonceStore(ttl_seconds=10, max_entries=100)
    t = 1_000_000.0
    assert ns.check_and_record("n1", now=t) is True
    # After TTL expires, the entry is evicted and re-accepted.
    assert ns.check_and_record("n1", now=t + 11) is True


def test_nonce_store_bounded_size():
    ns = NonceStore(ttl_seconds=10**9, max_entries=3)
    for i in range(5):
        ns.check_and_record(f"n{i}")
    # Only the latest 3 should remain.
    assert ns.check_and_record("n0") is True   # evicted, re-accepted
    assert ns.check_and_record("n1") is True   # evicted, re-accepted
    assert ns.check_and_record("n4") is False  # still in store