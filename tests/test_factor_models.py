"""Unit tests for the theory-grounded factor frameworks."""

from scanner import factor_models as FM


STRONG_CURR = {"roa": 0.12, "fcf": 900, "ni": 700, "gross_margin": 0.45,
               "asset_turnover": 0.9, "leverage": 0.2, "current_ratio": 2.1, "shares": 100}
STRONG_PRIOR = {"roa": 0.09, "fcf": 600, "ni": 650, "gross_margin": 0.42,
                "asset_turnover": 0.85, "leverage": 0.25, "current_ratio": 1.8, "shares": 101}
STRONG_M = {"forward_pe": 13, "pb": 1.3, "current_ratio": 2.1, "dividend_yield": 0.02,
            "earnings_growth": 0.1, "debt_to_equity": 0.4, "roa": 0.12, "operating_margin": 0.2}


def test_piotroski_perfect_score():
    p = FM.piotroski(STRONG_CURR, STRONG_PRIOR)
    assert p["score"] == 9 and p["max"] == 9


def test_piotroski_drops_missing_checks():
    p = FM.piotroski({"roa": 0.1, "ni": 5, "fcf": 9}, {"roa": 0.05})
    # Only checks with both inputs present are counted.
    assert p["max"] < 9
    assert "current_ratio_rising" not in p["checks"]


def test_graham_full_pass():
    g = FM.graham(STRONG_M)
    assert g["passed"] == g["total"] and g["total"] >= 6


def test_greenblatt_approximate_signal():
    gb = FM.greenblatt(STRONG_M)
    assert gb["approximate"] is True
    assert gb["earnings_yield"] is not None
    assert gb["signal"] == 1.0  # cheap + high ROC


def test_evaluate_combines_and_degrades():
    full = FM.evaluate(STRONG_M, STRONG_CURR, STRONG_PRIOR)
    assert full["available"] and full["framework_score"] > 80
    # No history -> Piotroski absent but Graham/Greenblatt still available.
    snap = FM.evaluate(STRONG_M)
    assert snap["available"]
    assert snap["piotroski"]["max"] == 0


def test_evaluate_empty_unavailable():
    out = FM.evaluate({})
    # No PE/PB/etc -> Graham/Greenblatt produce nothing usable.
    assert out["framework_score"] is None
    assert out["available"] is False
