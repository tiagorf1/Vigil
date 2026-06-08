"""Automatic horizon selection.

You should not pick how far Kronos forecasts — the *opportunity* should. We
forecast each name at several horizons (short / medium / long) and pick the
operative one as the shortest horizon where the (calibrated) forecast is
confident AND agrees with the technical setup. The horizon class then falls out
of that choice:

    operative ~10d  -> "low"     (short-term / day-trade-like)
    operative ~30d  -> "medium"  (swing)
    operative ~60d+ -> "high"    (position / long-term)

Rationale: Kronos is most reliable at short horizons; a long horizon is only
"the call" if the short ones don't already give a confident, TA-aligned read.
"""

from __future__ import annotations


def _class_for(horizon: int, horizons: list[int]) -> str:
    lo = min(horizons)
    hi = max(horizons)
    if horizon <= lo:
        return "low"
    if horizon >= hi:
        return "high"
    return "medium"


def select(forecasts_by_h: dict[int, dict], ta: dict | None,
           horizons: list[int], conf_min: float = 0.08) -> dict:
    """`forecasts_by_h`: {horizon: forecast_dict} for ONE symbol.

    Returns the operative horizon, its class, whether TA agrees, a confidence,
    and a compact term-structure for display.
    """
    hs = sorted(h for h in horizons if h in forecasts_by_h and forecasts_by_h[h])
    if not hs:
        return {"horizon_days": None, "horizon_class": "medium", "agrees": False,
                "confidence": 0.0, "term_structure": []}

    trend_up = None
    if ta and ta.get("trend"):
        trend_up = ta["trend"] == "up"

    term = []
    for h in hs:
        fc = forecasts_by_h[h]
        exp = fc.get("expected_return_pct")
        prob = fc.get("prob_up")
        conf = abs(prob - 0.5) * 2 if isinstance(prob, (int, float)) else 0.0  # 0..1
        up = (exp or 0) > 0
        agrees = (trend_up is None) or (up == trend_up)
        term.append({"days": h, "expected_return_pct": exp, "prob_up": prob,
                     "confidence": round(conf, 3), "ta_agrees": agrees,
                     "class": _class_for(h, hs)})

    # Operative = shortest horizon that is confident AND agrees with TA.
    operative = next((t for t in term if t["confidence"] >= conf_min and t["ta_agrees"]), None)
    if operative is None:
        # none confident+aligned -> take the most confident horizon, flag weak.
        operative = max(term, key=lambda t: t["confidence"])
        operative = {**operative, "weak": True}

    return {
        "horizon_days": operative["days"],
        "horizon_class": operative["class"],
        "agrees": bool(operative.get("ta_agrees", False)),
        "confidence": operative["confidence"],
        "weak": bool(operative.get("weak", False)),
        "term_structure": term,
    }
