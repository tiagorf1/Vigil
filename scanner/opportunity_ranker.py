"""Rank opportunities by risk posture.

This is deliberately separate from the generic Vigil score. A single idea can be
unattractive for a conservative sleeve and compelling for a speculative sleeve.
The ranker makes that explicit instead of forcing every pick through one moral
view of risk.
"""

from __future__ import annotations


PROFILES = ("conservative", "balanced", "aggressive", "speculative")


def score_item(item: dict) -> dict:
    report = item.get("report") or {}
    forecast = item or {}
    sizing = report.get("_sizing") or {}
    barrier = report.get("_barrier") or {}
    ta = report.get("_ta") or {}
    tags = {str(t).lower() for t in item.get("tags", [])}
    score = _num(item.get("score"), 0.0)
    pwin = _num(sizing.get("p_win_used"), None)
    if pwin is None:
        prob_up = _num(item.get("prob_up"), None)
        pwin = (1 - prob_up) if item.get("direction") == "short" and prob_up is not None else prob_up
    expected_r = _num(sizing.get("expected_r"), _num(barrier.get("expected_r"), None))
    exp = _num(item.get("expected_return_pct"), 0.0)
    q95 = _num(item.get("ret_q95_pct"), None)
    q05 = _num(item.get("ret_q05_pct"), None)
    vol = _num(item.get("terminal_vol_pct"), None)
    rr = _num(ta.get("rr_value"), _rr(item.get("risk_reward")))
    weight = _num(sizing.get("weight_pct"), 0.0)
    conf = _num(sizing.get("confidence_multiplier"), 1.0)
    conviction = _num(item.get("conviction"), 3.0) / 5.0 * 100.0

    trust_penalty = 0.0
    if "data_warning" in tags:
        trust_penalty += 18
    if "earnings_in_window" in tags:
        trust_penalty += 14
    if forecast.get("calibration_generation") and forecast.get("calibration_generation") != "sample_backed":
        trust_penalty += 8
    counter = "counter_trend" in tags
    no_edge = sizing.get("binding") == "no_edge" or (expected_r is not None and expected_r <= 0)

    conservative = (
        0.36 * score
        + 0.18 * conviction
        + 0.18 * _prob_score(pwin)
        + 0.16 * _er_score(expected_r)
        + 0.12 * _low_vol_score(vol)
        - trust_penalty
        - (10 if counter else 0)
        - (30 if no_edge else 0)
    )
    balanced = (
        0.44 * score
        + 0.18 * _prob_score(pwin)
        + 0.20 * _er_score(expected_r)
        + 0.10 * _rr_score(rr)
        + 0.08 * min(100.0, weight * 6)
        - trust_penalty * 0.45
        - (12 if no_edge else 0)
    )
    aggressive = (
        0.30 * score
        + 0.18 * _abs_return_score(exp)
        + 0.24 * _er_score(expected_r)
        + 0.18 * _rr_score(rr)
        + 0.10 * _tail_score(q05, q95, item.get("direction"))
        - trust_penalty * 0.25
        + (5 if counter else 0)
        - (8 if no_edge else 0)
    )
    speculative = (
        0.18 * score
        + 0.26 * _tail_score(q05, q95, item.get("direction"))
        + 0.20 * _rr_score(rr)
        + 0.18 * _abs_return_score(exp)
        + 0.12 * _vol_score(vol)
        + 0.06 * _er_score(expected_r)
        - (18 if "data_warning" in tags else 0)
        + (8 if counter else 0)
    )

    rows = {
        "conservative": _row(conservative * conf, [
            "best for cleaner evidence, lower event/data risk, and positive level-based edge",
            _flag(no_edge, "no-edge sizing blocks this sleeve"),
            _flag(counter, "counter-trend lowers conservative fit"),
        ]),
        "balanced": _row(balanced * (0.7 + 0.3 * conf), [
            "best all-around read: score, probability, expected R, and risk/reward",
            _flag(no_edge, "sizing says no positive expectancy"),
        ]),
        "aggressive": _row(aggressive, [
            "best for stronger payoff asymmetry and larger forecasted move",
            _flag(counter, "counter-trend can be a feature here, not a bug"),
        ]),
        "speculative": _row(speculative, [
            "best for convex/tail payoff; expect noise and smaller sizing",
            _flag("data_warning" in tags, "data warning still matters even for speculation"),
        ]),
    }
    best = max(rows, key=lambda k: rows[k]["score"])
    return {"profiles": rows, "best_profile": best}


def apply_ranks(items: list[dict]) -> None:
    for item in items:
        item["opportunity"] = score_item(item)
    for profile in PROFILES:
        ranked = sorted(items, key=lambda x: x["opportunity"]["profiles"][profile]["score"], reverse=True)
        for i, item in enumerate(ranked, start=1):
            item["opportunity"]["profiles"][profile]["rank"] = i


def _row(score: float, reasons: list[str | None]) -> dict:
    return {
        "score": round(_clamp(score), 1),
        "rank": None,
        "reasons": [r for r in reasons if r],
    }


def _flag(condition: bool, text: str) -> str | None:
    return text if condition else None


def _num(value, default):
    return value if isinstance(value, (int, float)) else default


def _clamp(x: float) -> float:
    return max(0.0, min(100.0, float(x)))


def _prob_score(p) -> float:
    if not isinstance(p, (int, float)):
        return 50.0
    return _clamp(p * 100.0)


def _er_score(er) -> float:
    if not isinstance(er, (int, float)):
        return 45.0
    return _clamp(50.0 + er * 25.0)


def _rr_score(rr) -> float:
    if not isinstance(rr, (int, float)):
        return 45.0
    return _clamp(rr / 4.0 * 100.0)


def _low_vol_score(vol) -> float:
    if not isinstance(vol, (int, float)):
        return 50.0
    return _clamp(100.0 - vol * 3.0)


def _vol_score(vol) -> float:
    if not isinstance(vol, (int, float)):
        return 45.0
    return _clamp(vol * 3.0)


def _abs_return_score(exp) -> float:
    if not isinstance(exp, (int, float)):
        return 45.0
    return _clamp(abs(exp) * 5.0)


def _tail_score(q05, q95, direction) -> float:
    tail = q95 if direction != "short" else (-q05 if isinstance(q05, (int, float)) else None)
    if not isinstance(tail, (int, float)):
        return 45.0
    return _clamp(tail * 4.0)


def _rr(value) -> float | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    try:
        return float(value.split(":", 1)[1])
    except ValueError:
        return None
