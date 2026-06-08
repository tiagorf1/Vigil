"""TA entry/exit engine."""

import pandas as pd

from scanner import entry_exit


def _uptrend(n=160, base=100.0, slope=0.4):
    rows, price = [], base
    d = pd.Timestamp("2024-01-01")
    for i in range(n):
        o = price; c = price + slope
        rows.append({"ts": (d + pd.Timedelta(days=i)).isoformat(),
                     "open": o, "high": max(o, c) + 0.3, "low": min(o, c) - 0.3,
                     "close": c, "volume": 1000})
        price = c
    return rows


def test_analyze_uptrend_levels():
    a = entry_exit.analyze(_uptrend())
    assert a["setup"] is not None
    assert a["trend"] == "up"
    assert a["confluence"] >= 1
    # stop below price, target above (rr positive)
    assert a["rr_value"] is None or a["rr_value"] > 0
    assert a["entry_zone"] and a["stop"] and a["target"]


def test_analyze_short_history_safe():
    a = entry_exit.analyze([{"ts": "2024-01-01", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}])
    assert a["setup"] is None  # not enough data, no crash
