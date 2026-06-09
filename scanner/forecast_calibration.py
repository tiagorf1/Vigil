"""Apply empirical forecast calibration to raw Kronos output.

The backtest (`scanner.backtest`) measures, per (asset_class, horizon), how
biased the model's return forecast is and how wide the error distribution really
is. This module applies those corrections to a live forecast so the displayed
numbers are honest:

  * de-bias the central return,
  * shrink overstated return magnitudes toward zero,
  * set the cone width from the *real* error stdev (not the model's tight cloud),
  * recompute prob_up with a normal approximation (so it stops pinning to 0/100).

If no calibration file exists yet, forecasts pass through unchanged but flagged
`calibrated: False` so the UI can say so.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache

from scanner.config import get_config

_Z95 = 1.96


def _clamp_prob(p):
    """No real forecast is ever a literal 0%/100%. Keep prob_up in a sane band."""
    try:
        return round(min(0.98, max(0.02, float(p))), 4)
    except (TypeError, ValueError):
        return p


# Shipped default calibration (from an early walk-forward backtest). Far better
# than Kronos's raw overconfident cone; a user's own `outputs/forecast_calibration.json`
# (regenerate via `python -m scanner.backtest`) overrides this entirely.
# NOTE: add_pct (mean de-bias) is intentionally 0 here. A non-zero shift measured
# from a tiny backtest (n~20) is unreliable and was visibly INFLATING already-bullish
# forecasts (e.g. MSFT +20%). We keep only the cone-WIDENING (sigma), which is the
# robust, believability-improving part. Run `python -m scanner.backtest` to write a
# real outputs/forecast_calibration.json with trustworthy, sample-backed add_pct.
_DEFAULT_CALIBRATION = {
    "equity":    {"20": {"add_pct": 0.0, "sigma_pct": 12.0, "shrink_factor": 0.45, "n": 0}},
    "etf":       {"20": {"add_pct": 0.0, "sigma_pct": 9.0, "shrink_factor": 0.50, "n": 0}},
    "index":     {"20": {"add_pct": 0.0, "sigma_pct": 8.5, "shrink_factor": 0.50, "n": 0}},
    "crypto":    {"20": {"add_pct": 0.0, "sigma_pct": 13.0, "shrink_factor": 0.55, "n": 0}},
    "commodity": {"20": {"add_pct": 0.0, "sigma_pct": 7.0, "shrink_factor": 0.50, "n": 0}},
    "forex":     {"20": {"add_pct": 0.0, "sigma_pct": 1.5, "shrink_factor": 0.45, "n": 0}},
}


@lru_cache(maxsize=1)
def _load() -> dict:
    path = get_config().project_root / "outputs" / "forecast_calibration.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:  # noqa: BLE001
            pass
    return _DEFAULT_CALIBRATION


def reload() -> None:
    _load.cache_clear()


def _lookup(cal: dict, asset_class: str, horizon: int) -> dict | None:
    bucket = cal.get(asset_class)
    if not bucket:
        # fall back to any class average
        allf = [v for b in cal.values() for v in b.values()]
        if not allf:
            return None
        return {"add_pct": sum(f["add_pct"] for f in allf) / len(allf),
                "sigma_pct": sum(f["sigma_pct"] for f in allf) / len(allf),
                "shrink_factor": sum(f.get("shrink_factor", 1.0) for f in allf) / len(allf),
                "n": sum(f.get("n", 0) for f in allf)}
    # nearest horizon
    hs = sorted(bucket.keys(), key=lambda h: abs(int(h) - horizon))
    return bucket[hs[0]]


def apply(fc: dict, asset_class: str, horizon: int) -> dict:
    if not fc:
        return fc
    factors = _lookup(_load(), asset_class, horizon)
    fc = dict(fc)
    raw_exp = fc.get("expected_return_pct") or 0.0
    fc["raw_prob_up"] = fc.get("prob_up")
    if not factors:
        # No empirical calibration file yet. Still de-pin prob_up using the model's
        # OWN terminal vol so it never reports an unrealistic 0%/100% (Kronos's raw
        # path-fraction pins to 0/1 on a small sample). Honest, even uncalibrated.
        fc["calibrated"] = False
        sigma = fc.get("terminal_vol_pct")
        if isinstance(sigma, (int, float)) and sigma > 1e-6:
            z = raw_exp / sigma
            fc["prob_up"] = 0.5 * (1 + math.erf(z / math.sqrt(2)))
        fc["prob_up"] = _clamp_prob(fc.get("prob_up"))
        fc["calibration_generation"] = "uncalibrated"
        return fc

    add = float(factors["add_pct"])         # percentage points to add to return
    sigma = float(factors["sigma_pct"])     # true terminal stdev, in %
    shrink = _clamp_shrink(factors.get("shrink_factor", 1.0))
    cur = fc.get("current_close")

    fc["raw_expected_return_pct"] = raw_exp
    bias_adjusted = raw_exp + add
    exp = bias_adjusted * shrink
    fc["bias_adjusted_expected_return_pct"] = round(bias_adjusted, 4)
    fc["shrink_factor"] = shrink
    fc["expected_return_pct"] = round(exp, 4)

    if sigma > 1e-6:
        z = exp / sigma
        fc["prob_up"] = _clamp_prob(0.5 * (1 + math.erf(z / math.sqrt(2))))
        fc["ret_q50_pct"] = round(exp, 4)
        fc["ret_q05_pct"] = round(exp - _Z95 * sigma, 4)
        fc["ret_q95_pct"] = round(exp + _Z95 * sigma, 4)
        fc["terminal_vol_pct"] = round(sigma, 4)

    if cur:
        model_sigma = fc.get("raw_terminal_vol_pct") or fc.get("terminal_vol_pct") or sigma
        scale = (sigma / model_sigma) if model_sigma and model_sigma > 1e-6 else 1.0
        cone = fc.get("cone") or {}
        q50, q05, q95 = cone.get("q50"), cone.get("q05"), cone.get("q95")
        if q50 and q05 and q95 and len(q50) == len(q05) == len(q95):
            nq05, nq50, nq95 = [], [], []
            for i in range(len(q50)):
                raw_step_ret = (q50[i] / cur - 1.0) * 100.0
                step_ret = (raw_step_ret + add) * shrink
                m = cur * (1 + step_ret / 100.0)
                nq50.append(round(m, 6))
                nq05.append(round(m + (q05[i] - q50[i]) * scale, 6))
                nq95.append(round(m + (q95[i] - q50[i]) * scale, 6))
            fc["cone"] = {"q05": nq05, "q50": nq50, "q95": nq95}
        fc["forecast_close"] = round(cur * (1 + exp / 100.0), 6)
        fc["forecast_high"] = round(cur * (1 + (exp + _Z95 * sigma) / 100.0), 6)
        fc["forecast_low"] = round(cur * (1 + (exp - _Z95 * sigma) / 100.0), 6)

    fc["calibrated"] = True
    fc["calibration_n"] = factors.get("n")
    fc["calibration_generation"] = "sample_backed" if (factors.get("n") or 0) > 0 else "default_prior"
    return fc


def _clamp_shrink(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 1.0
    return round(min(1.0, max(0.05, v)), 4)
