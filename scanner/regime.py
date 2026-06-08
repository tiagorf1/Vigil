"""Market-regime conditioning — risk-on vs risk-off context for the whole scan.

The same setup means different things in different weather. We classify a coarse
regime from the most reliable free gauge — the VIX level and its trend — plus the
dollar/yield context when available. The regime is surfaced as a banner and a tag
so you read every pick through it (favour momentum/breakout in risk-on, prefer
mean-reversion/quality in risk-off). Deliberately conservative: it informs, it
does not silently rewrite the scores.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("scanner.regime")


def classify(vix: float | None, vix_sma: float | None = None,
             macro: dict | None = None) -> dict:
    drivers: list[str] = []
    score = 0   # positive = risk-on

    if isinstance(vix, (int, float)):
        if vix < 15:
            score += 2; drivers.append(f"VIX {vix:.0f} (calm)")
        elif vix < 20:
            score += 1; drivers.append(f"VIX {vix:.0f}")
        elif vix < 26:
            drivers.append(f"VIX {vix:.0f} (elevated)")
        else:
            score -= 2; drivers.append(f"VIX {vix:.0f} (stressed)")
        if isinstance(vix_sma, (int, float)) and vix_sma > 0:
            if vix > vix_sma * 1.1:
                score -= 1; drivers.append("VIX rising")
            elif vix < vix_sma * 0.9:
                score += 1; drivers.append("VIX falling")

    regime = "risk_on" if score >= 2 else ("risk_off" if score <= -2 else "neutral")
    tilt = {
        "risk_on": "favour momentum / breakout",
        "risk_off": "favour mean-reversion / quality, widen stops",
        "neutral": "no strong tilt",
    }[regime]
    return {"regime": regime, "score": score, "drivers": drivers, "tilt": tilt,
            "vix": vix, "vix_sma": vix_sma}


async def detect(macro: dict | None = None) -> dict:
    """Fetch VIX (free) and classify. Best-effort; returns neutral on failure."""
    vix = vix_sma = None
    try:
        from scanner import market_data
        rows = await market_data.fallback_ohlcv("^VIX", bars=60)
        closes = [r.get("close") for r in (rows or []) if r.get("close") is not None]
        if closes:
            vix = round(closes[-1], 2)
            tail = closes[-20:]
            vix_sma = round(sum(tail) / len(tail), 2)
    except Exception as exc:  # noqa: BLE001
        logger.debug("VIX fetch failed: %s", exc)
    return classify(vix, vix_sma, macro)
