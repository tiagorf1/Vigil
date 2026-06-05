"""Disk TTL cache."""

import time

from scanner.cache import DiskCache


def test_set_get_roundtrip():
    c = DiskCache("test_ns", ttl_seconds=60)
    c.clear()
    c.set("profile:AAPL", {"name": "Apple"})
    assert c.get("profile:AAPL") == {"name": "Apple"}


def test_miss_returns_none():
    c = DiskCache("test_ns", ttl_seconds=60)
    assert c.get("nonexistent:key") is None


def test_ttl_expiry():
    c = DiskCache("test_ns_ttl", ttl_seconds=1)
    c.clear()
    c.set("k", {"v": 1})
    assert c.get("k") == {"v": 1}
    time.sleep(1.2)
    assert c.get("k") is None
