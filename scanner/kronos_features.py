"""Higher-order signals derived from the Kronos forecast cloud.

The predictor already emits path-intrinsic features (vol, range, MAE/MFE, skew,
CVaR, vol-trend, risk-adjusted return) in forecast["features"]. This module adds
the LEVEL-aware and CROSS-asset signals:

* barrier_probabilities() — P(price touches your target before your stop), the
  real probability behind an R:R. Reconstructs a path ensemble from the forecast
  cone (drift = median path, vol = cone width) and first-passage simulates.
* vol_edge() — predicted realized vol vs option-implied vol (rich/cheap).
* kronos_quality() — a 0-100 quality score from Kronos alone, for assets with no
  fundamentals (FX / crypto / commodities) where price dynamics ARE the thesis.
"""

from __future__ import annotations

import math

import numpy as np


def _to_price(v, current):
    return v if v is not None else current


def barrier_probabilities(forecast: dict, entry: float, stop: float,
                          target: float, n_sims: int = 3000) -> dict:
    """P(touch target before stop) within the horizon, from the forecast cone."""
    out = {"p_target_first": None, "p_stop_first": None, "p_neither": None,
           "expected_days_to_target": None, "expected_r": None}
    cone = (forecast or {}).get("cone") or {}
    q50 = cone.get("q50"); q05 = cone.get("q05"); q95 = cone.get("q95")
    cur = forecast.get("current_close")
    if not (q50 and q05 and q95 and cur) or not (entry and stop and target):
        return out
    n = len(q50)
    med = np.array([cur] + list(q50))
    lo = np.array([cur] + list(q05))
    hi = np.array([cur] + list(q95))
    drift = np.diff(med)                                   # per-step drift
    sigma_cum = (hi - lo) / (2 * 1.96)                     # cumulative std per step
    sigma_cum = np.clip(sigma_cum, 1e-9, None)
    step_var = np.diff(sigma_cum ** 2)
    step_sd = np.sqrt(np.clip(step_var, 1e-12, None))      # incremental vol

    rng = np.random.default_rng(7)
    shocks = rng.standard_normal((n_sims, n))
    price = np.full(n_sims, float(cur))
    hit_t = np.zeros(n_sims, dtype=bool)
    hit_s = np.zeros(n_sims, dtype=bool)
    touch_step = np.zeros(n_sims)
    long = target > entry
    for t in range(n):
        price = price + drift[t] + step_sd[t] * shocks[:, t]
        if long:
            newt = (~hit_t) & (~hit_s) & (price >= target)
            news = (~hit_t) & (~hit_s) & (price <= stop)
        else:
            newt = (~hit_t) & (~hit_s) & (price <= target)
            news = (~hit_t) & (~hit_s) & (price >= stop)
        touch_step[newt] = t + 1
        hit_t |= newt
        hit_s |= news

    pt = float(hit_t.mean()); ps = float(hit_s.mean())
    out.update({
        "p_target_first": round(pt, 3),
        "p_stop_first": round(ps, 3),
        "p_neither": round(1 - pt - ps, 3),
        "expected_days_to_target": round(float(touch_step[hit_t].mean()), 1) if hit_t.any() else None,
        # Expected R-multiple (probability-weighted): R_target * p_target - 1 * p_stop.
        # NOT a probability — can exceed 1. Positive = favourable expectancy.
        "expected_r": round(((target - entry) / max(entry - stop, 1e-9)) * pt - ps, 2) if long
                      else round(((entry - target) / max(stop - entry, 1e-9)) * pt - ps, 2),
    })
    return out


def vol_edge(forecast: dict, implied_vol_annual: float | None, horizon_days: int) -> dict:
    """Compare Kronos predicted realized vol to option-implied vol."""
    f = (forecast or {}).get("features") or {}
    tv = forecast.get("terminal_vol_pct")
    if tv is None or implied_vol_annual is None or horizon_days <= 0:
        return {"predicted_vol_pct": tv, "implied_vol_pct": None, "vol_edge": None}
    # Scale implied annual vol to the horizon.
    implied_h = implied_vol_annual * math.sqrt(horizon_days / 252.0) * 100
    edge = tv - implied_h   # >0: market underpricing vol (buy options); <0: rich (sell)
    return {"predicted_vol_pct": round(tv, 2), "implied_vol_pct": round(implied_h, 2),
            "vol_edge": round(edge, 2),
            "vol_call": "options cheap (vol underpriced)" if edge > 2
                        else ("options rich (vol overpriced)" if edge < -2 else "fair")}


def kronos_quality(forecast: dict) -> tuple[float, dict]:
    """0-100 quality from Kronos alone — for FX/crypto/commodities (no fundamentals).
    Rewards: positive risk-adjusted return, directional confidence, favorable skew,
    and a clean (not blow-off) volatility regime."""
    if not forecast:
        return 0.0, {}
    f = forecast.get("features") or {}
    prob = forecast.get("prob_up")
    rvr = f.get("ret_vol_ratio")
    skew = f.get("skew")
    mae = f.get("mae_pct")
    cvar = f.get("cvar5_pct")

    score = 0.0
    bd = {}
    # Directional confidence (max 35)
    if isinstance(prob, (int, float)):
        bd["direction"] = round(min(35, abs(prob - 0.5) * 2 * 35), 1)
        score += bd["direction"]
    # Risk-adjusted expected return (max 30)
    if isinstance(rvr, (int, float)):
        bd["risk_adjusted"] = round(max(0, min(30, (rvr + 0.2) * 60)), 1)
        score += bd["risk_adjusted"]
    # Favorable asymmetry / skew (max 15)
    if isinstance(skew, (int, float)):
        bd["skew"] = round(max(0, min(15, (skew + 0.5) * 10)), 1)
        score += bd["skew"]
    # Downside containment (max 20): smaller CVaR / MAE is better
    if isinstance(cvar, (int, float)):
        bd["downside"] = round(max(0, min(20, 20 + cvar)), 1)  # cvar negative
        score += bd["downside"]
    return round(min(score, 100.0), 1), bd
