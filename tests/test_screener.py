"""Screener scoring with the local-indicator pipeline (mocked OpenAlice)."""

import pandas as pd
import pytest

from scanner.screener import Screener, _num, _text


def _series(n=260, base=100.0, slope=0.5, vol=1000):
    rows, price = [], base
    d = pd.Timestamp("2024-01-01")
    for i in range(n):
        o = price
        c = price + slope
        rows.append({"ts": (d + pd.Timedelta(days=i)).isoformat(),
                     "open": o, "high": max(o, c) + 0.2, "low": min(o, c) - 0.2,
                     "close": c, "volume": vol})
        price = c
    return rows


class FakeClient:
    def __init__(self, ohlcv, profile=None, financials=None, ratios=None,
                 estimates=None, insider=None):
        self._ohlcv = ohlcv
        self._profile = profile or {}
        self._financials = financials or {}
        self._ratios = ratios or {}
        self._estimates = estimates or {}
        self._insider = insider or {}

    async def get_ohlcv(self, s, interval="1d", bars=400): return self._ohlcv
    async def get_profile(self, s): return self._profile
    async def get_financials(self, s): return self._financials
    async def get_ratios(self, s): return self._ratios
    async def get_analyst_estimates(self, s): return self._estimates
    async def get_insider_trading(self, s): return self._insider


@pytest.fixture(autouse=True)
def _no_network_fundamentals(monkeypatch):
    """Force the OpenAlice fallback path so screener tests never hit Yahoo."""
    async def _f(symbol, use_cache=True):
        return {}
    import scanner.fundamentals as F
    monkeypatch.setattr(F, "fetch", _f)


def test_helpers():
    assert _num({"pe": "18.5"}, "pe") == 18.5
    assert _num({}, "pe") is None
    assert _text({"sector": "Technology"}, "sector") == "Technology"


@pytest.mark.asyncio
async def test_equity_fundamentals_full_score(monkeypatch):
    # Force the OpenAlice fallback path (no network): real fundamentals provider
    # returns nothing, so the screener scores from the mocked OpenAlice fields.
    async def _no_yahoo(symbol, use_cache=True):
        return {}
    import scanner.fundamentals as F
    monkeypatch.setattr(F, "fetch", _no_yahoo)

    client = FakeClient(
        ohlcv=_series(),
        profile={"companyName": "Test Co", "sector": "Technology"},
        financials={"revenueGrowth": 0.15, "netIncome": 100},
        ratios={"peRatio": 20, "debtToEquity": 1.0},
        estimates={"consensus": "Buy", "epsSurprise": 2.0},
        insider={"netShares": 1000},
    )
    survivors = await Screener(client).screen(["TEST"], asset_class="equity")
    c = survivors[0]
    assert c.fund_score == 100.0            # all fundamental factors hit
    assert c.sector == "Technology"
    # Uptrend: price above both SMAs and MACD positive -> technicals score.
    assert c.tech_score >= 25.0
    assert c.indicators["price"] is not None


@pytest.mark.asyncio
async def test_weak_name_zero_fundamentals():
    client = FakeClient(
        ohlcv=_series(slope=-0.5),  # downtrend
        financials={"revenueGrowth": -0.2, "netIncome": -10},
        ratios={"peRatio": 80, "debtToEquity": 5.0},
        estimates={"consensus": "Sell", "epsSurprise": -3.0},
        insider={"netShares": -500},
    )
    c = (await Screener(client).screen(["WEAK"], asset_class="equity"))[0]
    assert c.fund_score == 0.0


@pytest.mark.asyncio
async def test_crypto_momentum_score():
    series = _series(n=40, slope=1.0)
    series[-1]["volume"] = 100000  # volume spike on the latest bar
    client = FakeClient(ohlcv=series)
    c = (await Screener(client).screen(["BTCUSD"], asset_class="crypto"))[0]
    # 25 free + 25 (30d up) + 25 (7d up) + 25 (vol spike) = 100
    assert c.fund_score == 100.0
