"""prob_up must never pin to a literal 0%/100%."""

from scanner import forecast_calibration as FC


def test_calibrated_prob_never_pins():
    fc = {"expected_return_pct": -16.4, "prob_up": 0.0, "terminal_vol_pct": 2.2,
          "current_close": 290, "cone": {"q05": [280], "q50": [285], "q95": [290]}}
    out = FC.apply(dict(fc), "equity", 10)
    assert 0.02 <= out["prob_up"] <= 0.98
    assert out["prob_up"] != 0.0


def test_uncalibrated_class_still_depins_and_clamps():
    out = FC.apply({"expected_return_pct": -16.4, "prob_up": 0.0, "terminal_vol_pct": 2.2},
                   "totally_unknown_class_xyz", 10)
    assert out["prob_up"] >= 0.02
