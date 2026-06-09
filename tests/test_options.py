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
                               "expected_move_pct": 5.0, "put_call_oi_ratio": 0.7,
                               "atm_open_interest": 500, "atm_spread_pct": 4.0})
    out = asyncio.run(OPT.analyze("X", FORECAST, 30))
    assert out["has_options"] is True
    assert out["vol_edge"] > 2          # underpriced
    assert "call" in out["idea"].lower()
    assert 0 <= out["p_above_call_strike"] <= 1
    assert out["hygiene"]["usable"] is True


def test_probabilities_track_direction(monkeypatch):
    _patch_chain(monkeypatch, {"has_options": True, "spot": 100, "atm_iv": 0.30,
                               "expected_move_pct": 6.0, "atm_open_interest": 500})
    out = asyncio.run(OPT.analyze("X", FORECAST, 30))
    # Bullish drift -> more likely to exceed the up-strike than break the down-strike.
    assert out["p_above_call_strike"] > out["p_below_put_strike"]


def test_options_hygiene_flags_thin_wide_chains(monkeypatch):
    _patch_chain(monkeypatch, {"has_options": True, "spot": 100, "atm_iv": 0.30,
                               "expected_move_pct": 6.0, "atm_open_interest": 5,
                               "atm_spread_pct": 25.0})
    out = asyncio.run(OPT.analyze("X", FORECAST, 30))
    assert out["hygiene"]["usable"] is False
    assert any("open interest" in f for f in out["hygiene"]["flags"])
    assert any("spread" in f for f in out["hygiene"]["flags"])


def test_non_option_asset_returns_reason():
    out = asyncio.run(OPT.analyze("BTCUSD", FORECAST, 30))
    assert out["has_options"] is False
    assert "no supported options" in out["reason"]
