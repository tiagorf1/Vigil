"""Two-stage screener: fundamental + technical.

Technicals are computed locally (scanner.indicators) from a single OHLCV fetch
per symbol rather than via per-indicator MCP round-trips. The OHLCV is stashed
on the Candidate and reused for Kronos, so survivors are never re-fetched.

Scores are tolerant of missing data — an unmeasurable factor contributes 0.
If too few names clear both thresholds, we rank all by combined score so the
pipeline still produces a watchlist (logged when it triggers).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from scanner import indicators
from scanner.config import get_config

logger = logging.getLogger("scanner.screener")

FUND_THRESHOLD = 40.0
TECH_THRESHOLD = 45.0
_CONCURRENCY = 8


@dataclass
class Candidate:
    symbol: str
    asset_class: str = "equity"
    fund_score: float = 0.0
    tech_score: float = 0.0
    indicators: dict = field(default_factory=dict)
    profile: dict = field(default_factory=dict)
    financials: dict = field(default_factory=dict)
    ratios: dict = field(default_factory=dict)
    analyst_estimates: dict = field(default_factory=dict)
    insider_trading: dict = field(default_factory=dict)
    earnings: dict = field(default_factory=dict)
    news: list = field(default_factory=list)
    ohlcv: list = field(default_factory=list)
    sector: str = ""

    @property
    def combined(self) -> float:
        return self.fund_score + self.tech_score

    @property
    def passed(self) -> bool:
        return self.fund_score >= FUND_THRESHOLD and self.tech_score >= TECH_THRESHOLD


class Screener:
    def __init__(self, client):
        self.client = client
        self.cfg = get_config()
        self._sem = asyncio.Semaphore(_CONCURRENCY)

    async def screen(self, symbols: list[str], asset_class: str = "equity") -> list[Candidate]:
        tasks = [self._screen_one(s, asset_class) for s in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        candidates: list[Candidate] = []
        for sym, res in zip(symbols, results):
            if isinstance(res, Exception):
                logger.warning("Screen failed for %s: %s", sym, res)
            elif res is not None:
                candidates.append(res)

        passed = [c for c in candidates if c.passed]
        if len(passed) >= 3:
            pool = passed
            logger.info("%d/%d cleared both screens", len(passed), len(candidates))
        else:
            pool = candidates
            logger.warning("Only %d cleared both screens — lenient ranking of all %d",
                           len(passed), len(candidates))

        pool.sort(key=lambda c: c.combined, reverse=True)
        survivors = pool[: self.cfg.max_screened_size]
        logger.info("Screener survivors: %d", len(survivors))
        return survivors

    async def _screen_one(self, symbol: str, asset_class: str) -> Candidate | None:
        async with self._sem:
            c = Candidate(symbol=symbol, asset_class=asset_class)
            # One OHLCV fetch drives all technicals (and crypto momentum).
            c.ohlcv = await self.client.get_ohlcv(
                symbol, interval="1d", bars=self.cfg.default_lookback + 60)
            c.indicators = indicators.compute_all(c.ohlcv)

            if asset_class in ("crypto", "index", "etf", "commodity", "forex"):
                self._score_fundamental_momentum(c)
            else:
                await self._score_fundamental_equity(c)
            self._score_technical(c)
            return c

    # ── fundamental: equity ───────────────────────────────────────────────
    async def _score_fundamental_equity(self, c: Candidate) -> None:
        profile, financials, ratios, estimates, insider = await asyncio.gather(
            self.client.get_profile(c.symbol),
            self.client.get_financials(c.symbol),
            self.client.get_ratios(c.symbol),
            self.client.get_analyst_estimates(c.symbol),
            self.client.get_insider_trading(c.symbol),
        )
        c.profile, c.financials, c.ratios = profile, financials, ratios
        c.analyst_estimates, c.insider_trading = estimates, insider
        c.sector = _text(profile, "sector", "industry", "gicsSector") or ""

        score = 0.0
        rev = _num(financials, "revenueGrowth", "revenue_growth_yoy", "revenueGrowthYoY", "revenueGrowthTTM")
        if rev is not None:
            if rev > 0:
                score += 15
            if rev > 0.10 or rev > 10:
                score += 10
        if (_num(financials, "netIncome", "net_income", "netIncomeTTM") or 0) > 0:
            score += 10
        pe = _num(ratios, "peRatio", "pe", "priceEarningsRatio", "peRatioTTM")
        if pe is not None and 0 < pe < 25:
            score += 10
        rating = _text(estimates, "consensus", "rating", "recommendation", "consensusRating")
        if rating and any(w in rating.lower() for w in ("buy", "outperform", "overweight", "strong")):
            score += 20
        if (_num(insider, "netShares", "net_buying", "netBuying", "netTransactionShares") or 0) > 0:
            score += 10
        de = _num(ratios, "debtToEquity", "debt_to_equity", "debtEquityRatio")
        if de is not None and de < 2:
            score += 10
        if (_num(estimates, "epsSurprise", "earningsSurprise", "lastSurprisePct") or 0) > 0:
            score += 15
        c.fund_score = min(score, 100.0)

    # ── momentum-based score for crypto / indexes / futures / FX ──────────
    def _score_fundamental_momentum(self, c: Candidate) -> None:
        ind = c.indicators
        score = 25.0  # fundamentals N/A -> free pass
        if (ind.get("ret_30d") or 0) > 0:
            score += 25
        if (ind.get("ret_7d") or 0) > 0:
            score += 25
        if (ind.get("vol_vs_avg") or 0) > 1:
            score += 25
        c.fund_score = min(score, 100.0)

    # ── technical (from local indicators) ─────────────────────────────────
    def _score_technical(self, c: Candidate) -> None:
        ind = c.indicators
        price = ind.get("price")
        rsi = ind.get("rsi14")
        hist = ind.get("macd_hist")
        hist_prev = ind.get("macd_hist_prev")
        sma50, sma200 = ind.get("sma50"), ind.get("sma200")
        bb_u, bb_l = ind.get("bb_upper"), ind.get("bb_lower")

        score = 0.0
        if rsi is not None:
            if 30 <= rsi <= 50:
                score += 20
            elif 50 < rsi <= 65:
                score += 15
        if hist is not None and hist > 0 and (hist_prev is None or hist > hist_prev):
            score += 20
        if price is not None and sma50 is not None and price > sma50:
            score += 15
        if price is not None and sma200 is not None and price > sma200:
            score += 10
        if price is not None and bb_l is not None and bb_u is not None:
            band = bb_u - bb_l
            if band > 0 and (price - bb_l) / band < 0.25:
                score += 20
        c.tech_score = min(score, 100.0)


# ── fundamental dict extraction helpers ────────────────────────────────────
def _num(d, *keys) -> float | None:
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d and d[k] is not None:
            try:
                return float(d[k])
            except (TypeError, ValueError):
                continue
    return None


def _text(d, *keys) -> str | None:
    if not isinstance(d, dict):
        return None
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return None
