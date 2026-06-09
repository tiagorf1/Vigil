"""prob_up must never pin to a literal 0%/100%."""

import json

from scanner import config, forecast_calibration as FC


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


def test_expected_return_is_shrunk_from_calibration(monkeypatch):
    monkeypatch.setattr(FC, "_load", lambda: {
        "equity": {"10": {"add_pct": 0.0, "sigma_pct": 10.0, "shrink_factor": 0.25, "n": 40}}
    })
    out = FC.apply({"expected_return_pct": 20.0, "prob_up": 0.9, "terminal_vol_pct": 4.0,
                    "current_close": 100, "cone": {"q05": [95], "q50": [120], "q95": [125]}},
                   "equity", 10)
    assert out["raw_expected_return_pct"] == 20.0
    assert out["bias_adjusted_expected_return_pct"] == 20.0
    assert out["shrink_factor"] == 0.25
    assert out["expected_return_pct"] == 5.0
    assert out["forecast_close"] == 105.0


def test_low_sample_file_calibration_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_PROJECT_ROOT", tmp_path)
    config.get_config.cache_clear()
    FC.reload()
    outdir = tmp_path / "outputs"
    outdir.mkdir()
    (outdir / "forecast_calibration.json").write_text(json.dumps({
        "equity": {"10": {"add_pct": 99.0, "sigma_pct": 1.0, "shrink_factor": 1.0, "n": 2}}
    }))
    out = FC.apply({"expected_return_pct": 20.0, "prob_up": 0.9, "terminal_vol_pct": 4.0,
                    "current_close": 100, "cone": {"q05": [95], "q50": [120], "q95": [125]}},
                   "equity", 10)
    assert out["expected_return_pct"] == 9.0  # default equity prior: 20% * 0.45
    assert out["calibration_generation"] == "default_prior_low_sample_fallback"
    assert out["ignored_calibration_n"] == 2
    FC.reload()
    config.get_config.cache_clear()


def test_sample_backed_file_calibration_is_used(monkeypatch):
    monkeypatch.setattr(FC, "_load", lambda: {
        "equity": {"10": {"add_pct": 1.0, "sigma_pct": 10.0, "shrink_factor": 0.5, "n": 40}}
    })
    out = FC.apply({"expected_return_pct": 20.0, "prob_up": 0.9, "terminal_vol_pct": 4.0},
                   "equity", 10)
    assert out["expected_return_pct"] == 10.5
    assert out["calibration_generation"] == "sample_backed"
