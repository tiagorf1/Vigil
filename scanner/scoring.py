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
    """Return (vigil_score 0-100, breakdown). Pure function, no I/O."""
    forecast = forecast or {}
    comps: list[tuple[str, float, float]] = []   # (name, score 0-100, weight)

    # 1) Analyst conviction — the holistic synthesis read.
    conv = report.get("conviction")
    if isinstance(conv, (int, float)):
        comps.append(("conviction", _clamp(conv / 5 * 100), 0.30))

    # 2) Barrier prob-weighted R — the real edge of YOUR levels vs the path cloud.
    barrier = report.get("_barrier") or {}
    pr = barrier.get("prob_R")
    if isinstance(pr, (int, float)):
        # prob_R ~[-1, +2] -> 0..100 (0 at -1, ~67 at +1, 100 at +2).
        comps.append(("barrier_R", _clamp((pr + 1) / 3 * 100), 0.22))
    pt, ps = barrier.get("p_target_first"), barrier.get("p_stop_first")
    if isinstance(pt, (int, float)) and isinstance(ps, (int, float)):
        comps.append(("barrier_edge", _clamp((pt - ps + 1) / 2 * 100), 0.10))

    # 3) Calibrated probability of up (meta-model) — falls back to raw prob_up.
    mp = report.get("_meta_prob_up")
    if isinstance(mp, (int, float)):
        comps.append(("meta_prob_up", _clamp(mp * 100), 0.15))
    else:
        pu = forecast.get("prob_up")
        if isinstance(pu, (int, float)):
            comps.append(("prob_up", _clamp(pu * 100), 0.12))

    # 4) Quality — Kronos-quality for price-only assets, else fundamental/technical.
    kq = report.get("_kronos_quality")
    if isinstance(kq, (int, float)):
        comps.append(("kronos_quality", _clamp(kq), 0.13))
    else:
        parts = [s for s in (fund_score, tech_score) if isinstance(s, (int, float))]
        if parts:
            comps.append(("screens", _clamp(sum(parts) / len(parts)), 0.13))

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
