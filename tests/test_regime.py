"""Unit tests for market-regime classification."""

from scanner import regime


def test_calm_vix_is_risk_on():
    r = regime.classify(12, vix_sma=15)
    assert r["regime"] == "risk_on"
    assert "momentum" in r["tilt"]


def test_stressed_vix_is_risk_off():
    r = regime.classify(30, vix_sma=24)
    assert r["regime"] == "risk_off"
    assert r["score"] <= -2


def test_mid_vix_is_neutral():
    r = regime.classify(21, vix_sma=21)
    assert r["regime"] == "neutral"


def test_missing_vix_is_neutral():
    r = regime.classify(None)
    assert r["regime"] == "neutral"
    assert r["drivers"] == []
