"""Options & volatility edge — where Kronos's real strength (path/vol) pays off.

Kronos forecasts a volatility cone, not just a direction. The options market
prices its OWN expected move via implied volatility. Comparing the two is a
genuine, differentiated signal:

* Kronos vol  >> implied vol  -> the market underprices movement: options CHEAP.
* Kronos vol  << implied vol  -> the market overprices movement: options RICH.

From the terminal forecast distribution we also derive P(price > strike), so an
option idea gets a real probability, not a hand-wave. All inputs are free (Yahoo
options chain, crumb-authed). Equities / ETFs / indexes only; price-only assets
(FX, crypto) usually have no usable chain and return {has_options: False}.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger("scanner.options")


def _phi(z: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _terminal_dist(forecast: dict) -> tuple[float, float, float] | None:
    """(spot, mu_terminal, sigma_terminal) in price units from the cone."""
    cone = (forecast or {}).get("cone") or {}
    q50, q05, q95 = cone.get("q50"), cone.get("q05"), cone.get("q95")
    cur = forecast.get("current_close")
    if not (q50 and q05 and q95 and cur):
        return None
    mu = float(q50[-1]); lo = float(q05[-1]); hi = float(q95[-1])
    sigma = max((hi - lo) / (2 * 1.96), 1e-9)
    return float(cur), mu, sigma


async def analyze(symbol: str, forecast: dict, horizon_days: int) -> dict:
    """Fetch the chain and compute the vol edge + probability-aware option idea."""
    from scanner import yahoo, kronos_features as KF
    try:
        chain = await yahoo.options_chain(symbol)
    except Exception as exc:  # noqa: BLE001
        logger.debug("options chain failed for %s: %s", symbol, exc)
        return {"has_options": False}
    if not chain or not chain.get("has_options"):
        return {"has_options": False}

    spot = chain.get("spot") or forecast.get("current_close")
    atm_iv = chain.get("atm_iv")                      # annualized, decimal
    implied_move_pct = chain.get("expected_move_pct")  # straddle-implied, horizon-ish

    out = {
        "has_options": True,
        "spot": spot,
        "atm_iv_pct": round(atm_iv * 100, 1) if isinstance(atm_iv, (int, float)) else None,
        "implied_move_pct": implied_move_pct,
        "put_call_oi_ratio": chain.get("put_call_oi_ratio"),
        "expirations": chain.get("expirations"),
    }

    # Kronos predicted move vs implied (vol edge), reusing the shared helper.
    ve = KF.vol_edge(forecast, atm_iv, horizon_days)
    out["kronos_vol_pct"] = ve.get("predicted_vol_pct")
    out["implied_vol_pct"] = ve.get("implied_vol_pct")
    out["vol_edge"] = ve.get("vol_edge")
    out["vol_call"] = ve.get("vol_call")

    # Probability the move exceeds what options price in (terminal distribution).
    dist = _terminal_dist(forecast)
    prob_up = forecast.get("prob_up")
    if dist and isinstance(implied_move_pct, (int, float)) and spot:
        cur, mu, sigma = dist
        up_k = cur * (1 + implied_move_pct / 100.0)
        dn_k = cur * (1 - implied_move_pct / 100.0)
        out["p_above_call_strike"] = round(1 - _phi((up_k - mu) / sigma), 3)
        out["p_below_put_strike"] = round(_phi((dn_k - mu) / sigma), 3)

    out["idea"] = _idea(out, prob_up)
    return out


def _idea(o: dict, prob_up) -> str:
    """One-line, honest option suggestion from vol edge + direction."""
    edge = o.get("vol_edge")
    cheap = isinstance(edge, (int, float)) and edge > 2
    rich = isinstance(edge, (int, float)) and edge < -2
    up = isinstance(prob_up, (int, float)) and prob_up >= 0.55
    dn = isinstance(prob_up, (int, float)) and prob_up <= 0.45

    if cheap and up:
        return "Vol underpriced + upward lean: long calls / call debit spread."
    if cheap and dn:
        return "Vol underpriced + downward lean: long puts / put debit spread."
    if cheap:
        return "Vol underpriced, direction unclear: long straddle / strangle."
    if rich and up:
        return "Vol overpriced + upward lean: sell cash-secured puts / put credit spread."
    if rich and dn:
        return "Vol overpriced + downward lean: sell call credit spread."
    if rich:
        return "Vol overpriced, no edge in direction: sell premium (iron condor)."
    return "Vol fairly priced: no clear options edge; trade the underlying."
