"""Unit tests for the options / volatility-edge module."""

import asyncio

import pytest

from scanner import options as OPT


FORECAST = {
    "current_close": 100, "prob_up": 0.62, "terminal_vol_pct": 18.0,
    "cone": {"q05": [95, 92, 88], "q50": [101, 103, 106], "q95": [107, 112, 120]},
}


def _patch_chain(monkeypatch, chain):
    import scanner.yahoo as Y

    async def fake(sym):
        return chain
    monkeypatch.setattr(Y, "options_chain", fake)


def test_no_chain_returns_has_options_false(monkeypatch):
    _patch_chain(monkeypatch, {"has_options": False})
    out = asyncio.run(OPT.analyze("X", FORECAST, 30))
    assert out == {"has_options": False}


def test_cheap_vol_with_upward_lean_suggests_calls(monkeypatch):
    # Kronos 18% vol vs implied ~8.7% (annual 0.30 over 30d) -> options cheap.
    _patch_chain(monkeypatch, {"has_options": True, "spot": 100, "atm_iv": 0.30,
                               "expected_move_pct": 5.0, "put_call_oi_ratio": 0.7})
    out = asyncio.run(OPT.analyze("X", FORECAST, 30))
    assert out["has_options"] is True
    assert out["vol_edge"] > 2          # underpriced
    assert "call" in out["idea"].lower()
    assert 0 <= out["p_above_call_strike"] <= 1


def test_probabilities_track_direction(monkeypatch):
    _patch_chain(monkeypatch, {"has_options": True, "spot": 100, "atm_iv": 0.30,
                               "expected_move_pct": 6.0})
    out = asyncio.run(OPT.analyze("X", FORECAST, 30))
    # Bullish drift -> more likely to exceed the up-strike than break the down-strike.
    assert out["p_above_call_strike"] > out["p_below_put_strike"]
