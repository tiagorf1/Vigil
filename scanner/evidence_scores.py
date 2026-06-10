"""Convert raw screen scores into evidence scores with visible confidence.

The raw fundamental and technical screens are useful, but they can saturate:
several names can hit 100/100 or cluster at the same technical bucket. This
module keeps the raw score, then blends it with peer rank and data confidence so
the number shown in reports behaves more like "strength of evidence" than a
checklist total.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable


_FUND_FIELDS = (
    "trailing_pe", "forward_pe", "peg", "pb", "ps", "profit_margin",
    "operating_margin", "gross_margin", "roe", "roa", "revenue_growth",
    "earnings_growth", "debt_to_equity", "current_ratio", "free_cashflow",
    "rev_net_30",
)

_TECH_FIELDS = (
    "rsi14", "macd_hist", "sma50", "sma200", "atr14", "bb_upper",
    "ret_1m", "ret_3m", "ret_6m", "ann_vol_pct", "dist_sma50_pct",
    "dist_sma200_pct", "max_drawdown_1y_pct",
)


def apply_to_candidates(candidates: Iterable[object]) -> None:
    """Mutate candidates in-place, preserving raw scores on raw_* attributes."""
    cands = list(candidates)
    if not cands:
        return

    raw_fund = [_num(getattr(c, "fund_score", None), 0.0) for c in cands]
    raw_tech = [_num(getattr(c, "tech_score", None), 0.0) for c in cands]
    fund_pct = _peer_percentiles(cands, raw_fund, "fund")
    tech_pct = _peer_percentiles(cands, raw_tech, "tech")

    for i, c in enumerate(cands):
        setattr(c, "raw_fund_score", round(raw_fund[i], 1))
        setattr(c, "raw_tech_score", round(raw_tech[i], 1))
        f_conf = _fund_confidence(getattr(c, "fundamentals", {}) or {})
        t_conf = _tech_confidence(getattr(c, "indicators", {}) or {})
        f_score = _evidence_score(raw_fund[i], fund_pct[i], f_conf)
        t_score = _evidence_score(raw_tech[i], tech_pct[i], t_conf)
        setattr(c, "fund_score", f_score)
        setattr(c, "tech_score", t_score)
        setattr(c, "evidence_scores", {
            "fundamental": {
                "raw": round(raw_fund[i], 1),
                "evidence": f_score,
                "peer_percentile": round(fund_pct[i], 1),
                "confidence": round(f_conf, 2),
            },
            "technical": {
                "raw": round(raw_tech[i], 1),
                "evidence": t_score,
                "peer_percentile": round(tech_pct[i], 1),
                "confidence": round(t_conf, 2),
            },
            "method": "raw screen blended with same-scan peer percentile and data confidence",
        })


def _peer_percentiles(cands: list[object], values: list[float], kind: str) -> list[float]:
    groups: dict[str, list[int]] = defaultdict(list)
    for i, c in enumerate(cands):
        groups[_group_key(c, kind)].append(i)
    out = [50.0 for _ in cands]
    for idxs in groups.values():
        if len(idxs) < 4:
            idxs = list(range(len(cands)))
        vals = [values[i] for i in idxs]
        for i in idxs:
            out[i] = _midrank_percentile(values[i], vals)
    return out


def _group_key(c: object, kind: str) -> str:
    ac = str(getattr(c, "asset_class", "") or "")
    if kind == "fund" and ac == "equity":
        sector = str(getattr(c, "sector", "") or "").strip().lower()
        return f"equity:{sector}" if sector else "equity"
    return ac or "all"


def _midrank_percentile(value: float, values: list[float]) -> float:
    if not values:
        return 50.0
    less = sum(1 for v in values if v < value)
    equal = sum(1 for v in values if v == value)
    return 100.0 * (less + 0.5 * equal) / len(values)


def _evidence_score(raw: float, percentile: float, confidence: float) -> float:
    # Confidence is a soft pull toward neutral, not a kill switch. A new venture
    # should not bury ideas just because the evidence set is still filling in.
    conf_pct = confidence * 100.0
    score = 0.58 * raw + 0.30 * percentile + 0.12 * conf_pct
    neutral_pull = (1.0 - confidence) * 0.18
    score = score * (1.0 - neutral_pull) + 50.0 * neutral_pull
    return round(max(0.0, min(100.0, score)), 1)


def _fund_confidence(fundamentals: dict) -> float:
    if fundamentals.get("note"):
        return 0.55
    present = sum(1 for k in _FUND_FIELDS if isinstance(fundamentals.get(k), (int, float)))
    base = present / len(_FUND_FIELDS)
    if fundamentals.get("_frameworks"):
        base += 0.12
    if fundamentals.get("source") == "fmp":
        base += 0.08
    return max(0.25, min(1.0, base))


def _tech_confidence(indicators: dict) -> float:
    present = sum(1 for k in _TECH_FIELDS if isinstance(indicators.get(k), (int, float)))
    return max(0.30, min(1.0, present / len(_TECH_FIELDS)))


def _num(value, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) else default
