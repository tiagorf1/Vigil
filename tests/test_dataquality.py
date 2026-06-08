"""Unit tests for data-quality guardrails."""

from scanner import dataquality as DQ


def _series(n=200, price=50.0):
    return [{"open": price, "high": price * 1.01, "low": price * 0.99,
             "close": price, "volume": 1000, "ts": i} for i in range(n)]


def test_insufficient_history_quarantines():
    out = DQ.analyze("X", _series(10))
    assert out["quarantine"] is True
    assert "insufficient_history" in out["flags"]


def test_clean_series_passes():
    rows = _series(200)
    # Add mild variation so it's not flagged flat.
    for i, r in enumerate(rows):
        bump = 1 + 0.01 * (i % 7)
        r["close"] = 50 * bump; r["high"] = r["close"] * 1.01; r["low"] = r["close"] * 0.99
    out = DQ.analyze("X", rows)
    assert out["ok"] is True
    assert out["quarantine"] is False


def test_penny_and_flat_flagged():
    rows = _series(200, price=0.4)   # penny + flat
    out = DQ.analyze("X", rows)
    assert "penny_stock" in out["flags"]
    assert out["quarantine"] is True   # flat triggers quarantine


def test_price_jump_flagged():
    rows = _series(200)
    for i, r in enumerate(rows):     # de-flatten
        r["close"] = 50 + (i % 5)
    rows[100]["close"] = rows[99]["close"] * 3   # 200% jump
    out = DQ.analyze("X", rows)
    assert any("price_jumps" in f for f in out["flags"])
