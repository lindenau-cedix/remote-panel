"""In-process token-bucket rate limiter, plus a nonce store for replay protection.

These are intentionally simple in-memory stores. They are good enough for a
single-process uvicorn worker. If you ever scale horizontally, swap the
backend for Redis.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class RateLimitConfig:
    capacity: int = 30        # tokens
    refill_per_sec: float = 0.5  # 30 tokens per minute = 0.5/sec


class TokenBucket:
    """One bucket per key (e.g. per remote IP)."""

    def __init__(self, cfg: RateLimitConfig) -> None:
        self._cfg = cfg
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[float, float]] = {}
        # value = (tokens, last_refill_ts)

    def allow(self, key: str, now: float | None = None) -> bool:
        ts = now if now is not None else time.monotonic()
        capacity = self._cfg.capacity
        refill = self._cfg.refill_per_sec
        with self._lock:
            tokens, last = self._buckets.get(key, (float(capacity), ts))
            tokens = min(capacity, tokens + (ts - last) * refill)
            if tokens >= 1.0:
                tokens -= 1.0
                self._buckets[key] = (tokens, ts)
                return True
            self._buckets[key] = (tokens, ts)
            return False


class NonceStore:
    """Stores seen nonces for replay protection. Memory-bounded."""

    def __init__(self, ttl_seconds: int = 600, max_entries: int = 100_000) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._lock = threading.Lock()
        self._seen: dict[str, float] = {}

    def check_and_record(self, nonce: str, now: float | None = None) -> bool:
        """Return True if the nonce is fresh (and records it), False if seen."""
        ts = now if now is not None else time.time()
        with self._lock:
            self._evict(ts)
            if nonce in self._seen:
                return False
            self._seen[nonce] = ts
            return True

    def _evict(self, now: float) -> None:
        cutoff = now - self._ttl
        # drop expired
        for k in [k for k, v in self._seen.items() if v < cutoff]:
            self._seen.pop(k, None)
        # bound size
        if len(self._seen) > self._max:
            # drop oldest
            for k in sorted(self._seen, key=lambda x: self._seen[x])[: len(self._seen) - self._max]:
                self._seen.pop(k, None)