"""Financial-coherence invariants — the self-check that catches silent math bugs.

The risk with a scoring/valuation engine is not that it's obviously wrong — it's
that a number is *quietly* wrong in a way a human won't catch, and the bug only
gets harder to spot as the output gets slicker. This module encodes the financial
and mathematical "laws" every pick must obey and runs them on every pick. A
violation is attached to the pick and surfaced loudly, so the engine self-reports
incoherence instead of relying on you to eyeball it.

These are invariants, not opinions: a long's stop must sit below its entry, the
barrier probabilities must sum to 1, a no-edge name must size to zero, the cone
must be ordered, and so on. The directional-probability bug we fixed would have
tripped `direction_score_matches_side` immediately.
"""

from __future__ import annotations


def _v(check: str, detail: str, value=None, severity: str = "error") -> dict:
    return {"check": check, "detail": detail, "value": value, "severity": severity}


def _num(x):
    return x if isinstance(x, (int, float)) else None


def audit(report: dict, forecast: dict | None) -> list[dict]:
    """Return a list of invariant violations for one assembled pick (empty = clean)."""
    out: list[dict] = []
    forecast = forecast or {}
    direction = report.get("direction", "long")
    is_long = direction != "short"
    ta = report.get("_ta") or {}
    entry, stop, target = _num(ta.get("entry_value")), _num(ta.get("stop_value")), _num(ta.get("target_value"))

    # 1) Trade-level ordering — the most basic structural law.
    if None not in (entry, stop, target):
        if is_long and not (stop < entry < target):
            out.append(_v("levels", "long requires stop < entry < target",
                          f"{stop} / {entry} / {target}"))
        if not is_long and not (stop > entry > target):
            out.append(_v("levels", "short requires stop > entry > target",
                          f"{stop} / {entry} / {target}"))
        # R:R must match the levels.
        rr = _num(ta.get("rr_value"))
        denom = abs(entry - stop)
        if rr is not None and denom > 1e-9:
            calc = abs(target - entry) / denom
            if abs(calc - rr) > 0.2:
                out.append(_v("levels", "stated R:R inconsistent with the levels",
                              f"stated {rr}, implied {calc:.2f}"))

    # 2) Direction must match the forecast it was chosen from.
    pu = _num(forecast.get("prob_up"))
    if pu is not None:
        if is_long and pu < 0.35:
            out.append(_v("direction", "long trade on a bearish forecast", f"prob_up={pu}", "warn"))
        if not is_long and pu > 0.65:
            out.append(_v("direction", "short trade on a bullish forecast", f"prob_up={pu}", "warn"))

    # 3) Direction score must be side-correct (the exact bug we fixed).
    bd = report.get("_score_breakdown") or {}
    dscore = _num(bd.get("direction_prob"))
    if dscore is not None and pu is not None:
        expected = (pu if is_long else (1 - pu)) * 100
        if abs(dscore - expected) > 1.5:
            out.append(_v("score", "direction_prob not computed for the trade side",
                          f"shown {dscore}, expected {expected:.0f}"))

    # 4) Barrier probabilities must be a valid distribution.
    b = report.get("_barrier") or {}
    pt, ps, pn = _num(b.get("p_target_first")), _num(b.get("p_stop_first")), _num(b.get("p_neither"))
    if None not in (pt, ps, pn):
        if abs((pt + ps + pn) - 1.0) > 0.02:
            out.append(_v("barrier", "P(target)+P(stop)+P(neither) != 1", f"sum={pt+ps+pn:.3f}"))
        for nm, val in (("p_target_first", pt), ("p_stop_first", ps), ("p_neither", pn)):
            if not (0 <= val <= 1):
                out.append(_v("barrier", f"{nm} outside [0,1]", val))

    # 5) Sizing must be bounded and zero when there is no edge.
    sz = report.get("_sizing") or {}
    w = _num(sz.get("weight_pct"))
    if w is not None:
        if not (0 <= w <= 25.001):
            out.append(_v("sizing", "suggested weight outside [0,25]%", w))
        if sz.get("binding") == "no_edge" and w > 0.01:
            out.append(_v("sizing", "no_edge but weight > 0", w))

    # 6) Forecast return quantiles must be ordered.
    q5, q50, q95 = _num(forecast.get("ret_q05_pct")), _num(forecast.get("ret_q50_pct")), _num(forecast.get("ret_q95_pct"))
    if None not in (q5, q50, q95) and not (q5 <= q50 <= q95):
        out.append(_v("forecast", "return quantiles not ordered (q05<=q50<=q95)", f"{q5}/{q50}/{q95}"))

    # 7) Cone must be ordered at the terminal step.
    cone = forecast.get("cone") or {}
    try:
        if cone.get("q05") and cone.get("q50") and cone.get("q95"):
            if not (cone["q05"][-1] <= cone["q50"][-1] <= cone["q95"][-1]):
                out.append(_v("forecast", "terminal cone not ordered (q05<=q50<=q95)",
                              f'{cone["q05"][-1]}/{cone["q50"][-1]}/{cone["q95"][-1]}'))
    except (IndexError, TypeError):
        pass

    # 8) Ranges.
    conv = _num(report.get("conviction"))
    if conv is not None and not (1 <= conv <= 5):
        out.append(_v("report", "conviction outside 1-5", conv))
    sc = _num(report.get("_score"))
    if sc is not None and not (0 <= sc <= 100):
        out.append(_v("score", "Vigil score outside 0-100", sc))
    p = _num(forecast.get("prob_up"))
    if p is not None and not (0 <= p <= 1):
        out.append(_v("forecast", "prob_up outside [0,1]", p))

    return out
