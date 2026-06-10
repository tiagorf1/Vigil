from dataclasses import dataclass, field

from scanner import evidence_scores


@dataclass
class C:
    symbol: str
    fund_score: float
    tech_score: float
    asset_class: str = "equity"
    sector: str = "Technology"
    fundamentals: dict = field(default_factory=dict)
    indicators: dict = field(default_factory=dict)


def _fund():
    return {
        "trailing_pe": 20, "forward_pe": 18, "roe": 0.2, "roa": 0.08,
        "profit_margin": 0.15, "revenue_growth": 0.1, "earnings_growth": 0.15,
        "debt_to_equity": 0.6, "current_ratio": 1.8, "free_cashflow": 100,
    }


def _ind():
    return {
        "rsi14": 55, "macd_hist": 1, "sma50": 100, "sma200": 90, "atr14": 2,
        "bb_upper": 120, "ret_1m": 4, "ret_3m": 8, "ret_6m": 10,
        "ann_vol_pct": 20, "dist_sma50_pct": 2, "dist_sma200_pct": 8,
        "max_drawdown_1y_pct": -12,
    }


def test_evidence_scores_preserve_raw_and_reduce_identical_saturation():
    cands = [C(f"S{i}", 100, 40, fundamentals=_fund(), indicators=_ind()) for i in range(5)]
    evidence_scores.apply_to_candidates(cands)

    assert all(c.raw_fund_score == 100 for c in cands)
    assert all(c.fund_score < 100 for c in cands)
    assert all(c.evidence_scores["fundamental"]["peer_percentile"] == 50 for c in cands)


def test_evidence_scores_respect_peer_order():
    cands = [
        C("A", 30, 20, fundamentals=_fund(), indicators=_ind()),
        C("B", 50, 40, fundamentals=_fund(), indicators=_ind()),
        C("C", 70, 60, fundamentals=_fund(), indicators=_ind()),
        C("D", 90, 80, fundamentals=_fund(), indicators=_ind()),
    ]
    evidence_scores.apply_to_candidates(cands)

    assert cands[0].fund_score < cands[-1].fund_score
    assert cands[0].tech_score < cands[-1].tech_score
