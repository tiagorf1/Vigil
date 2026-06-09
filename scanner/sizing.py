"""Position sizing — turn a watchlist into an allocatable basket.

We already compute everything sizing needs: a win probability (barrier
P(target-first), or calibrated prob_up), the asymmetric payoff (TA target/stop
distances), and forward volatility. From those:

* Fractional Kelly  — f* = (p·b − q) / b, where b = win/loss odds. Full Kelly is
  too aggressive and assumes a known edge, so we scale by SIZING_KELLY_FRACTION
  (default half-Kelly) and clamp to [0, 25%].
* Vol target        — size so the position's own volatility ≈ SIZING_TARGET_VOL.
* Suggested weight   = min(fractional Kelly, vol-target weight). The binding
  constraint wins, so a high-conviction but very volatile name is still capped.

If VIGIL_ACCOUNT_EQUITY is set, we also output a dollar amount. Advisory only.
"""

from __future__ import annotations

import math


def kelly_fraction(p_win: float, win_pct: float, loss_pct: float) -> float:
    """Full-Kelly fraction of capital. win_pct/loss_pct are positive magnitudes."""
    if not (0 < p_win < 1) or win_pct <= 0 or loss_pct <= 0:
        return 0.0
    b = win_pct / loss_pct           # payoff odds
    q = 1 - p_win
    f = (p_win * b - q) / b
    return max(0.0, f)


def suggest(p_win, win_pct, loss_pct, vol_annual_pct,
            equity: float = 0.0, kelly_fraction_used: float = 0.5,
            target_vol: float = 0.15, max_weight: float = 0.25,
            confidence_multiplier: float = 1.0, no_edge_reason: str | None = None) -> dict:
    """Return a sizing recommendation. All percentages are fractions of equity.

    Logic: fractional Kelly is the BASE weight (0 when there's no edge); the vol
    target and max_weight are CAPS on top of it. So a no-edge name gets ~0%, and
    the vol target only ever pulls a high-edge name DOWN — it can never invent a
    position where Kelly says there's no expectancy."""
    out = {"kelly_full": None, "weight_pct": None, "vol_target_pct": None,
           "dollar": None, "rationale": None, "binding": None,
           "confidence_multiplier": round(float(confidence_multiplier or 1.0), 3)}

    if no_edge_reason:
        out.update({"weight_pct": 0.0, "dollar": 0.0 if equity and equity > 0 else None,
                    "binding": "no_edge", "rationale": no_edge_reason})
        return out

    have_payoff = (isinstance(p_win, (int, float)) and 0 < p_win < 1
                   and isinstance(win_pct, (int, float)) and win_pct > 0
                   and isinstance(loss_pct, (int, float)) and loss_pct > 0)

    # Uncapped vol-target weight, so we can tell whether the binding constraint is
    # really the vol target or the hard max-position limit (they can coincide).
    vt_raw = None
    if isinstance(vol_annual_pct, (int, float)) and vol_annual_pct > 0:
        vt_raw = target_vol / (vol_annual_pct / 100.0)

    if have_payoff:
        f_full = kelly_fraction(p_win, win_pct, loss_pct)        # 0 if no edge
        out["kelly_full"] = round(f_full, 4)
        if f_full <= 0:
            weight, binding = 0.0, "no_edge"
        else:
            cands = {"kelly": f_full * kelly_fraction_used, "max_position": max_weight}
            if vt_raw is not None:
                cands["vol_target"] = vt_raw
            binding = min(cands, key=cands.get)                  # the smallest constraint wins
            weight = cands[binding]
    elif vt_raw is not None:
        cands = {"vol_target": vt_raw, "max_position": max_weight}
        binding = min(cands, key=cands.get)
        weight = cands[binding]
    else:
        return out

    conf = max(0.0, min(1.0, float(confidence_multiplier or 1.0)))
    weight = max(0.0, min(weight, max_weight)) * conf
    kf = int(kelly_fraction_used * 100)
    rationale = {
        "no_edge": "no positive expectancy -> no position",
        "kelly": f"{kf}% Kelly (edge-limited)",
        "vol_target": f"{kf}% Kelly trimmed to the {int(target_vol*100)}% volatility target",
        "max_position": f"{kf}% Kelly capped at the {int(max_weight*100)}% max-position limit",
    }[binding]
    if conf < 1.0 and binding != "no_edge":
        rationale += f"; confidence haircut x{conf:.2f}"
    out.update({
        "weight_pct": round(weight * 100, 2),
        "vol_target_pct": round(min(vt_raw, max_weight) * 100, 2) if vt_raw is not None else None,
        "binding": binding,
        "rationale": rationale,
    })
    if equity and equity > 0:
        out["dollar"] = round(weight * equity, 2)
    return out


def from_pick(report: dict, forecast: dict | None, equity: float = 0.0,
              kelly_fraction_used: float = 0.5, target_vol: float = 0.15) -> dict:
    """Derive sizing inputs from a pick's barrier/TA/forecast and call suggest()."""
    forecast = forecast or {}
    barrier = report.get("_barrier") or {}
    ta = report.get("_ta") or {}
    direction = report.get("direction", "long")
    is_short = direction == "short"

    no_edge_reason = None
    er = barrier.get("expected_r")
    if isinstance(er, (int, float)) and er <= 0:
        no_edge_reason = f"barrier expected R {er} <= 0 -> no position"

    # Win probability: prefer the path-cloud barrier prob, else calibrated/raw prob_up.
    p_win = barrier.get("p_target_first")
    if not isinstance(p_win, (int, float)):
        p_win = report.get("_meta_prob_up")
        if isinstance(p_win, (int, float)) and is_short:
            p_win = 1.0 - p_win
    if not isinstance(p_win, (int, float)):
        p_win = forecast.get("prob_up")
        if isinstance(p_win, (int, float)) and is_short:
            p_win = 1.0 - p_win

    # Asymmetric payoff from the TA plan.
    entry = ta.get("entry_value"); stop = ta.get("stop_value"); target = ta.get("target_value")
    win_pct = loss_pct = None
    if all(isinstance(x, (int, float)) for x in (entry, stop, target)) and entry:
        win_pct = abs(target - entry) / entry * 100
        loss_pct = abs(entry - stop) / entry * 100

    vol = forecast.get("terminal_vol_pct")
    # terminal_vol is horizon vol; annualize roughly for the vol target comparison.
    horizon = report.get("_horizon_days") or 20
    vol_annual = vol * math.sqrt(252.0 / horizon) if isinstance(vol, (int, float)) and horizon else vol

    conf = _confidence_multiplier(report, forecast)
    out = suggest(p_win, win_pct, loss_pct, vol_annual, equity,
                  kelly_fraction_used, target_vol,
                  confidence_multiplier=conf, no_edge_reason=no_edge_reason)
    out["p_win_used"] = round(p_win, 4) if isinstance(p_win, (int, float)) else None
    out["expected_r"] = er
    return out


def _confidence_multiplier(report: dict, forecast: dict) -> float:
    """Size haircut for uncertainty, without suppressing opportunity ranking."""
    tags = {str(t).lower() for t in report.get("tags", [])}
    mult = 1.0
    cal_gen = forecast.get("calibration_generation")
    if cal_gen and cal_gen != "sample_backed":
        mult *= 0.85
    if "earnings_in_window" in tags:
        mult *= 0.70
    if "data_warning" in tags:
        mult *= 0.75
    return round(mult, 4)
