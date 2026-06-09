"""Unit tests for position sizing."""

from scanner import sizing


def test_kelly_positive_edge():
    # 60% win, 2:1 payoff -> positive Kelly.
    f = sizing.kelly_fraction(0.6, win_pct=10, loss_pct=5)
    assert f > 0


def test_kelly_no_edge_is_zero():
    # 40% win, 1:1 payoff -> negative edge clamped to 0.
    assert sizing.kelly_fraction(0.4, win_pct=5, loss_pct=5) == 0.0


def test_suggest_vol_target_can_bind():
    # Very high vol should pull the weight down via the vol target.
    out = sizing.suggest(0.7, win_pct=12, loss_pct=4, vol_annual_pct=80,
                         equity=100_000, target_vol=0.15)
    assert out["weight_pct"] is not None
    assert out["weight_pct"] <= 25.0
    assert out["dollar"] is not None


def test_suggest_returns_empty_without_inputs():
    out = sizing.suggest(None, None, None, None)
    assert out["weight_pct"] is None


def test_from_pick_uses_barrier_prob_and_ta():
    report = {
        "_barrier": {"p_target_first": 0.55},
        "_ta": {"entry_value": 100, "stop_value": 95, "target_value": 115},
        "_horizon_days": 20,
    }
    out = sizing.from_pick(report, {"terminal_vol_pct": 8.0}, equity=50_000)
    assert out["weight_pct"] is not None
    assert out["dollar"] is not None


def test_no_edge_gives_zero_not_voltarget():
    # Bad payoff/low win prob -> no edge -> 0% (not the vol-target fallback).
    out = sizing.suggest(0.30, win_pct=5, loss_pct=10, vol_annual_pct=30, equity=100_000)
    assert out["weight_pct"] == 0.0
    assert out["binding"] == "no_edge"
    assert out["dollar"] == 0.0


def test_strong_edge_capped_by_max_weight():
    out = sizing.suggest(0.65, win_pct=15, loss_pct=5, vol_annual_pct=30)
    assert out["weight_pct"] <= 25.0
    assert out["weight_pct"] > 0
