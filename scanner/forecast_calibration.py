"""Apply empirical forecast calibration to raw Kronos output.

The backtest (`scanner.backtest`) measures, per (asset_class, horizon), how
biased the model's return forecast is and how wide the error distribution really
is. This module applies those corrections to a live forecast so the displayed
numbers are honest:

  * de-bias the central return,
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


@lru_cache(maxsize=1)
def _load() -> dict:
    path = get_config().project_root / "outputs" / "forecast_calibration.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return {}


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
                "n": sum(f.get("n", 0) for f in allf)}
    # nearest horizon
    hs = sorted(bucket.keys(), key=lambda h: abs(int(h) - horizon))
    return bucket[hs[0]]


def apply(fc: dict, asset_class: str, horizon: int) -> dict:
    if not fc:
        return fc
    factors = _lookup(_load(), asset_class, horizon)
    fc = dict(fc)
    if not factors:
        fc["calibrated"] = False
        return fc

    add = float(factors["add_pct"])         # percentage points to add to return
    sigma = float(factors["sigma_pct"])     # true terminal stdev, in %
    cur = fc.get("current_close")
    raw_exp = fc.get("expected_return_pct") or 0.0

    fc["raw_expected_return_pct"] = raw_exp
    fc["raw_prob_up"] = fc.get("prob_up")
    exp = raw_exp + add
    fc["expected_return_pct"] = round(exp, 4)

    if sigma > 1e-6:
        z = exp / sigma
        fc["prob_up"] = round(0.5 * (1 + math.erf(z / math.sqrt(2))), 4)
        fc["ret_q50_pct"] = round(exp, 4)
        fc["ret_q05_pct"] = round(exp - _Z95 * sigma, 4)
        fc["ret_q95_pct"] = round(exp + _Z95 * sigma, 4)
        fc["terminal_vol_pct"] = round(sigma, 4)

    if cur:
        addfrac = add / 100.0
        model_sigma = fc.get("raw_terminal_vol_pct") or fc.get("terminal_vol_pct") or sigma
        scale = (sigma / model_sigma) if model_sigma and model_sigma > 1e-6 else 1.0
        cone = fc.get("cone") or {}
        q50, q05, q95 = cone.get("q50"), cone.get("q05"), cone.get("q95")
        if q50 and q05 and q95 and len(q50) == len(q05) == len(q95):
            nq05, nq50, nq95 = [], [], []
            for i in range(len(q50)):
                m = q50[i] * (1 + addfrac)
                nq50.append(round(m, 6))
                nq05.append(round(m + (q05[i] - q50[i]) * scale, 6))
                nq95.append(round(m + (q95[i] - q50[i]) * scale, 6))
            fc["cone"] = {"q05": nq05, "q50": nq50, "q95": nq95}
        fc["forecast_close"] = round(cur * (1 + exp / 100.0), 6)
        fc["forecast_high"] = round(cur * (1 + (exp + _Z95 * sigma) / 100.0), 6)
        fc["forecast_low"] = round(cur * (1 + (exp - _Z95 * sigma) / 100.0), 6)

    fc["calibrated"] = True
    fc["calibration_n"] = factors.get("n")
    return fc
