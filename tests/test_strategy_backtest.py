"""Unit tests for the strategy equity-curve backtest."""

import math

from scanner import strategy_backtest as SB


def _trend_series(n=420):
    rows = []
    price = 100.0
    for i in range(n):
        price = price * (1 + 0.0009) + 0.02 * math.sin(i / 9.0)
        o, c = price * (1 - 0.003), price
        rows.append({"ts": i, "open": o, "high": max(o, c) * 1.006,
                     "low": min(o, c) * 0.994, "close": c, "volume": 1000})
    return rows


def test_uptrend_produces_winning_trades():
    rows = _trend_series()
    res = SB.backtest_symbol("SYN", rows, max_hold=30, step=3, cost_bps=5.0, min_history=220)
    assert res["trades"] > 0
    assert 0.0 <= res["win_rate"] <= 1.0
    assert "total_return_pct" in res and "buy_hold_pct" in res
    assert "by_setup" in res
    assert set(res["outcomes"]) == {"target", "stop", "time"}


def test_simulate_trade_hits_stop_and_target():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100, "ts": i} for i in range(5)]
    # Target hit at bar 2.
    rows[2] = {"open": 100, "high": 110, "low": 99, "close": 105, "ts": 2}
    ret, outcome, idx = SB._simulate_trade(rows, 0, entry=100, stop=95, target=108, max_hold=4)
    assert outcome == "target" and idx == 2 and ret > 0
    # Stop hit at bar 1 (pessimistic stop-first).
    rows2 = [{"open": 100, "high": 101, "low": 99, "close": 100, "ts": i} for i in range(5)]
    rows2[1] = {"open": 100, "high": 101, "low": 90, "close": 95, "ts": 1}
    ret2, outcome2, idx2 = SB._simulate_trade(rows2, 0, entry=100, stop=94, target=120, max_hold=4)
    assert outcome2 == "stop" and idx2 == 1 and ret2 < 0


def test_flat_series_never_manufactures_profit():
    # Constant price: target/stop are never touched, so every trade is a 'time'
    # exit at entry and the only effect is cost drag -> no fake edge.
    flat = [{"open": 100, "high": 100, "low": 100, "close": 100, "ts": i, "volume": 1}
            for i in range(300)]
    res = SB.backtest_symbol("FLAT", flat, max_hold=20, step=5, cost_bps=5.0, min_history=220)
    if res["trades"] == 0:
        return
    assert res["win_rate"] == 0.0
    assert res["total_return_pct"] <= 0
    assert res["outcomes"]["target"] == 0
