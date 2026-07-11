"""Append-only JSONL audit log.

One line per request, every line is a self-contained JSON object. The file is
opened in append-only mode and flushed after every write.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any


class AuditLog:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._fh = open(self._path, "a", encoding="utf-8", buffering=1)  # line-buffered

    def record(self, event: dict[str, Any]) -> None:
        event = {"ts": int(time.time()), **event}
        line = json.dumps(event, separators=(",", ":"), sort_keys=False, ensure_ascii=False)
        with self._lock:
            self._fh.write(line + "\n")

    def close(self) -> None:
        with self._lock:
            try:
                self._fh.close()
            except Exception:
                pass


# Module-level singleton; app.py may swap it out in tests.
_default: AuditLog | None = None


def set_default(log: AuditLog | None) -> None:
    global _default
    _default = log


def record(event: dict[str, Any]) -> None:
    if _default is not None:
        _default.record(event)
    # if no default configured, silently drop (tests can swap it in)