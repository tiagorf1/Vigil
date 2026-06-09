"""Composite 'Vigil score' — turns the gold the pipeline already computes into
the ranking signal.

Until now picks were ranked on (conviction, expected_return) only: the LLM's
holistic read plus a raw Kronos point estimate. But the pipeline also computes
barrier probabilities (P(target before stop) and a probability-weighted R from
the path cloud), a calibrated P(up) from the meta-model, and a Kronos-quality
score for price-only assets. Those were displayed but never moved the ranking.

`composite()` blends them transparently: each available component contributes a
0-100 sub-score with a weight; missing components are skipped and the remaining
weights renormalised, so a name with no options/meta data is still scored fairly
on what it does have. The breakdown is returned for explainability in the UI.
"""

from __future__ import annotations


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def composite(report: dict, forecast: dict | None,
              fund_score, tech_score) -> tuple[float, dict]:
    """Return (vigil_score 0-100, breakdown). Pure function, no I/O.

    The score is DIRECTION-correct (a confident bearish read scores a short HIGH,
    not low) and HORIZON-aware (fundamentals matter for position trades, barely for
    a low-horizon technical trade — long or short)."""
    forecast = forecast or {}
    direction = report.get("direction", "long")
    horizon = report.get("horizon", "medium")
    is_long = direction != "short"
    comps: list[tuple[str, float, float]] = []   # (name, score 0-100, weight)

    # 1) Analyst conviction — the holistic synthesis read.
    conv = report.get("conviction")
    if isinstance(conv, (int, float)):
        comps.append(("conviction", _clamp(conv / 5 * 100), 0.26))

    # 2) Directional probability (calibrated meta, else raw) — CORRECT for the
    #    chosen side. For a short, confidence in DOWN is (1 - prob_up).
    mp = report.get("_meta_prob_up")
    p = mp if isinstance(mp, (int, float)) else forecast.get("prob_up")
    if isinstance(p, (int, float)):
        p_dir = p if is_long else (1.0 - p)
        comps.append(("direction_prob", _clamp(p_dir * 100), 0.18))

    # 3) Barrier prob-weighted R — level-based, already side-correct (the barrier
    #    sim uses target<entry for shorts).
    barrier = report.get("_barrier") or {}
    pr = barrier.get("expected_r")
    if isinstance(pr, (int, float)):
        comps.append(("barrier_R", _clamp((pr + 1) / 3 * 100), 0.22))
    pt, ps = barrier.get("p_target_first"), barrier.get("p_stop_first")
    if isinstance(pt, (int, float)) and isinstance(ps, (int, float)):
        comps.append(("barrier_edge", _clamp((pt - ps + 1) / 2 * 100), 0.10))

    # 4) Technical alignment — confluence counts signals FOR the chosen side, so it
    #    is already direction-correct (bearish signals for a short).
    ta = report.get("_ta") or {}
    conf = ta.get("confluence")
    if isinstance(conf, (int, float)):
        comps.append(("technical", _clamp(conf / 5.0 * 100), 0.12))
    elif isinstance(tech_score, (int, float)):
        comps.append(("technical", _clamp(tech_score), 0.08))

    # 5) Quality. Price-only assets -> Kronos quality. Equities -> fundamentals,
    #    but WEIGHTED BY HORIZON: a low-horizon (technical) trade barely cares about
    #    fundamentals (weight 0), a long-term position cares fully. For a SHORT held
    #    long enough to be a fundamental call, weak fundamentals are the tailwind.
    kq = report.get("_kronos_quality")
    if isinstance(kq, (int, float)):
        comps.append(("kronos_quality", _clamp(kq), 0.12))
    elif isinstance(fund_score, (int, float)):
        hz_w = {"low": 0.0, "medium": 0.5, "high": 1.0}.get(horizon, 0.5)
        if hz_w > 0:
            fval = fund_score if is_long else (100 - fund_score)
            comps.append(("fundamentals", _clamp(fval), 0.12 * hz_w))

    if not comps:
        return 0.0, {}

    total_w = sum(w for _, _, w in comps)
    score = sum(s * w for _, s, w in comps) / total_w

    breakdown = {name: round(s, 1) for name, s, _ in comps}
    breakdown["_weights"] = {name: round(w / total_w, 2) for name, _, w in comps}

    # Penalty: the trade fights the price trend (forecast direction != trend).
    # This is the catch-a-falling-knife / catch-the-top case — heavily demote it.
    if report.get("_forecast_agrees") is False:
        score *= 0.70
        breakdown["_penalty"] = "counter_trend -30%"

    return round(_clamp(score), 1), breakdown
