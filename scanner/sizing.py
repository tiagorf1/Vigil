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
            target_vol: float = 0.15, max_weight: float = 0.25) -> dict:
    """Return a sizing recommendation. All percentages are fractions of equity.

    Logic: fractional Kelly is the BASE weight (0 when there's no edge); the vol
    target and max_weight are CAPS on top of it. So a no-edge name gets ~0%, and
    the vol target only ever pulls a high-edge name DOWN — it can never invent a
    position where Kelly says there's no expectancy."""
    out = {"kelly_full": None, "weight_pct": None, "vol_target_pct": None,
           "dollar": None, "rationale": None, "binding": None}

    have_payoff = (isinstance(p_win, (int, float)) and 0 < p_win < 1
                   and isinstance(win_pct, (int, float)) and win_pct > 0
                   and isinstance(loss_pct, (int, float)) and loss_pct > 0)

    vt = None
    if isinstance(vol_annual_pct, (int, float)) and vol_annual_pct > 0:
        vt = min(target_vol / (vol_annual_pct / 100.0), max_weight)

    if have_payoff:
        f_full = kelly_fraction(p_win, win_pct, loss_pct)        # 0 if no edge
        f_kelly = min(f_full * kelly_fraction_used, max_weight)
        weight = f_kelly if vt is None else min(f_kelly, vt)     # vol target = cap
        out["kelly_full"] = round(f_full, 4)
        if f_full <= 0:
            binding = "no_edge"
        elif vt is not None and vt < f_kelly:
            binding = "vol_target"
        else:
            binding = "kelly"
    elif vt is not None:
        weight = vt                                              # vol-only sizing
        binding = "vol_target"
    else:
        return out

    weight = max(0.0, min(weight, max_weight))
    out.update({
        "weight_pct": round(weight * 100, 2),
        "vol_target_pct": round(vt * 100, 2) if vt is not None else None,
        "binding": binding,
        "rationale": ("no positive expectancy -> no position" if binding == "no_edge"
                      else f"{int(kelly_fraction_used*100)}% Kelly capped by "
                           f"{'volatility target' if binding == 'vol_target' else 'edge'}"),
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

    # Win probability: prefer the path-cloud barrier prob, else calibrated/raw prob_up.
    p_win = barrier.get("p_target_first")
    if not isinstance(p_win, (int, float)):
        p_win = report.get("_meta_prob_up")
    if not isinstance(p_win, (int, float)):
        p_win = forecast.get("prob_up")

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

    return suggest(p_win, win_pct, loss_pct, vol_annual, equity,
                   kelly_fraction_used, target_vol)
