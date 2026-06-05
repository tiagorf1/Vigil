"""Tiny on-disk TTL cache for OpenAlice responses that are stable intraday.

Profiles, fundamentals, ratios, and earnings dates don't change minute to
minute. Caching them by (namespace, key, calendar-day) makes re-runs and
scheduled morning scans near-instant on the data-fetch stage.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

from scanner.config import get_config

logger = logging.getLogger("scanner.cache")


class DiskCache:
    def __init__(self, namespace: str, ttl_seconds: int = 86_400):
        cfg = get_config()
        self.dir = cfg.project_root / ".cache" / namespace
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl_seconds

    def _path(self, key: str) -> Path:
        h = hashlib.sha1(key.encode()).hexdigest()[:20]
        return self.dir / f"{h}.json"

    def get(self, key: str):
        p = self._path(key)
        if not p.exists():
            return None
        try:
            if time.time() - p.stat().st_mtime > self.ttl:
                return None
            payload = json.loads(p.read_text())
            return payload.get("value")
        except Exception:  # noqa: BLE001
            return None

    def set(self, key: str, value) -> None:
        try:
            self._path(key).write_text(json.dumps({"key": key, "value": value}, default=str))
        except Exception as exc:  # noqa: BLE001
            logger.debug("cache write failed for %s: %s", key, exc)

    def clear(self) -> int:
        n = 0
        for f in self.dir.glob("*.json"):
            f.unlink(missing_ok=True)
            n += 1
        return n
