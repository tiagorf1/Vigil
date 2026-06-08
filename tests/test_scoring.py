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
    assert "conviction" in bd and "barrier_R" in bd and "meta_prob_up" in bd
    # Weights renormalise to ~1.
    assert abs(sum(bd["_weights"].values()) - 1.0) < 0.02


def test_disagreement_applies_penalty():
    report = {"conviction": 4, "_kronos_quality": 70, "_forecast_agrees": False}
    with_pen, bd = scoring.composite(report, {"prob_up": 0.55}, None, None)
    report_ok = dict(report, _forecast_agrees=True)
    without_pen, _ = scoring.composite(report_ok, {"prob_up": 0.55}, None, None)
    assert with_pen < without_pen
    assert bd.get("_penalty")


def test_price_only_uses_kronos_quality_not_screens():
    report = {"conviction": 3, "_kronos_quality": 90}
    _, bd = scoring.composite(report, {"prob_up": 0.5}, None, None)
    assert "kronos_quality" in bd
    assert "screens" not in bd


def test_equity_uses_screens_when_no_kronos_quality():
    report = {"conviction": 3}
    _, bd = scoring.composite(report, {"prob_up": 0.5}, 60, 40)
    assert bd.get("screens") == 50.0  # mean of 60 and 40
