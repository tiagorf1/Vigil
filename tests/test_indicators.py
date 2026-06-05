"""Local technical-indicator math."""

import pandas as pd

from scanner import indicators as ind


def _uptrend(n=260, base=100.0, slope=0.5):
    rows = []
    price = base
    d = pd.Timestamp("2024-01-01")
    for i in range(n):
        o = price
        c = price + slope
        rows.append({"ts": (d + pd.Timedelta(days=i)).isoformat(),
                     "open": o, "high": max(o, c) + 0.2, "low": min(o, c) - 0.2,
                     "close": c, "volume": 1000 + i})
        price = c
    return rows


def test_sma_last_value():
    s = pd.Series([float(i) for i in range(1, 11)])
    assert ind.sma(s, 3).iloc[-1] == 9.0  # mean(8,9,10)


def test_rsi_all_up_is_max():
    s = pd.Series([float(i) for i in range(1, 40)])
    assert ind.rsi(s).iloc[-1] >= 99.0


def test_atr_positive():
    df = ind.ohlcv_to_frame(_uptrend(60))
    assert ind.atr(df).iloc[-1] > 0


def test_macd_hist_positive_in_uptrend():
    df = ind.ohlcv_to_frame(_uptrend(80))
    _, _, hist = ind.macd(df["close"])
    assert hist.iloc[-1] > 0


def test_compute_all_uptrend():
    out = ind.compute_all(_uptrend(260))
    assert out["price"] is not None
    assert out["sma50"] is not None and out["price"] > out["sma50"]
    assert out["sma200"] is not None and out["price"] > out["sma200"]
    assert out["rsi14"] > 70
    assert out["ret_30d"] > 0 and out["ret_7d"] > 0


def test_compute_all_empty_is_safe():
    out = ind.compute_all([])
    assert out["price"] is None and out["rsi14"] is None
