"""Unit tests for the composite Vigil score."""

from scanner import scoring


def test_empty_report_scores_zero():
    score, bd = scoring.composite({}, {}, None, None)
    assert score == 0.0
    assert bd == {}


def test_strong_name_scores_high():
    report = {
        "conviction": 5,
        "_barrier": {"prob_R": 1.5, "p_target_first": 0.6, "p_stop_first": 0.1},
        "_meta_prob_up": 0.7,
        "_forecast_agrees": True,
    }
    score, bd = scoring.composite(report, {"prob_up": 0.65}, 80, 80)
    assert score > 75
    assert "conviction" in bd and "barrier_R" in bd and "direction_prob" in bd
    # Weights renormalise to ~1.
    assert abs(sum(bd["_weights"].values()) - 1.0) < 0.02


def test_disagreement_applies_penalty():
    report = {"conviction": 4, "_kronos_quality": 70, "_forecast_agrees": False}
    with_pen, bd = scoring.composite(report, {"prob_up": 0.55}, None, None)
    report_ok = dict(report, _forecast_agrees=True)
    without_pen, _ = scoring.composite(report_ok, {"prob_up": 0.55}, None, None)
    assert with_pen < without_pen
    assert bd.get("_penalty")


def test_price_only_uses_kronos_quality():
    report = {"conviction": 3, "_kronos_quality": 90}
    _, bd = scoring.composite(report, {"prob_up": 0.5}, None, None)
    assert "kronos_quality" in bd
    assert "fundamentals" not in bd


def test_low_horizon_ignores_fundamentals():
    # A low-horizon (technical) trade should NOT be scored on fundamentals.
    rep = {"conviction": 3, "horizon": "low", "direction": "long"}
    _, bd = scoring.composite(rep, {"prob_up": 0.6}, 90, 50)
    assert "fundamentals" not in bd


def test_high_horizon_uses_fundamentals():
    rep = {"conviction": 3, "horizon": "high", "direction": "long"}
    _, bd = scoring.composite(rep, {"prob_up": 0.6}, 90, 50)
    assert bd.get("fundamentals") == 90.0


def test_short_directional_prob_is_inverted():
    # A short with a low P(up) is a CONFIDENT bearish read -> high direction score.
    rep = {"conviction": 3, "direction": "short"}
    _, bd = scoring.composite(rep, {"prob_up": 0.1}, None, None)
    assert bd.get("direction_prob") == 90.0


def test_low_horizon_short_not_punished_for_strong_fundamentals():
    # The user's case: a low-horizon short on a 100-fundamentals name should be
    # scored on technicals+forecast, NOT dragged down by good fundamentals.
    strong_fund_short = {"conviction": 3, "direction": "short", "horizon": "low",
                         "_barrier": {"prob_R": 0.9, "p_target_first": 0.55, "p_stop_first": 0.2}}
    s_strong, _ = scoring.composite(strong_fund_short, {"prob_up": 0.2}, 100, 50)
    weak_fund_short = dict(strong_fund_short)
    s_weak, _ = scoring.composite(weak_fund_short, {"prob_up": 0.2}, 10, 50)
    # Fundamentals are ignored at low horizon -> the two score the same.
    assert abs(s_strong - s_weak) < 0.01
