"""End-to-end integration test.

Requires a live OpenAlice MCP server and a runnable Kronos service.
Run with:  pytest tests/test_integration.py -v --integration
"""

import pytest

from scanner.config import get_config
from scanner.kronos_client import KronosClient
from scanner.openalice_client import OpenAliceClient
from scanner.report_generator import ReportGenerator
from scanner.screener import Screener

pytestmark = pytest.mark.integration

REQUIRED_KEYS = [
    "symbol", "name", "conviction", "thesis", "fundamental_summary",
    "technical_summary", "forecast_summary", "entry_zone", "stop_loss",
    "target", "risk_reward", "timeframe", "strategy_type", "risks", "tags",
]


@pytest.mark.asyncio
async def test_two_symbol_scan():
    cfg = get_config()
    symbols = ["AAPL", "MSFT"]
    kronos = KronosClient()
    await kronos.ensure_service_running()

    try:
        async with OpenAliceClient(cfg.openalice_mcp_url) as oa:
            survivors = await Screener(oa).screen(symbols, asset_class="equity")
            assert survivors, "screener returned no candidates"

            generator = ReportGenerator()
            for cand in survivors:
                ohlcv = await oa.get_ohlcv(cand.symbol, bars=cfg.default_lookback)
                forecast = await kronos.forecast(cand.symbol, ohlcv)
                news = await oa.get_news(cand.symbol, limit=3)
                report = generator.generate(
                    cand.symbol, cand.profile, cand.financials, cand.ratios,
                    cand.analyst_estimates, cand.insider_trading, cand.indicators,
                    news, forecast or {}, cand.fund_score, cand.tech_score,
                )
                for key in REQUIRED_KEYS:
                    assert key in report, f"missing {key}"
                assert 1 <= report["conviction"] <= 5
                assert isinstance(report["risks"], list)
    finally:
        kronos.shutdown()
