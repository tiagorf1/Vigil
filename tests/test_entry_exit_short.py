"""Short-setup sanity for the TA engine."""

import math

from scanner import entry_exit


def _downtrend(n=260):
    rows, p = [], 100.0
    for i in range(n):
        p = p * (1 - 0.0012) + 0.015 * math.sin(i / 8.0)
        o, c = p * 1.002, p
        rows.append({"ts": i, "open": o, "high": max(o, c) * 1.004,
                     "low": min(o, c) * 0.996, "close": c, "volume": 1000})
    return rows


def test_short_levels_are_inverted():
    ta = entry_exit.analyze(_downtrend(), direction="short")
    assert ta["direction"] == "short"
    assert ta["trend"] == "down"
    # Short: stop above entry, target below entry.
    assert ta["stop_value"] > ta["entry_value"] > ta["target_value"]
    assert ta["rr_value"] and ta["rr_value"] > 0


def test_long_levels_still_normal():
    rows, p = [], 100.0
    for i in range(260):
        p = p * (1 + 0.0012) + 0.015 * math.sin(i / 8.0)
        o, c = p * 0.998, p
        rows.append({"ts": i, "open": o, "high": max(o, c) * 1.004,
                     "low": min(o, c) * 0.996, "close": c, "volume": 1000})
    ta = entry_exit.analyze(rows, direction="long")
    assert ta["direction"] == "long"
    assert ta["stop_value"] < ta["entry_value"] < ta["target_value"]
