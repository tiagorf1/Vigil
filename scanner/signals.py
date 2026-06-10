"""Scheduled signal runner — your chosen markets + portfolio sell-check.

Reads SIGNAL_MARKETS (e.g. "us,crypto,commodities,forex,portfolio") and, for each:
  * a market keyword (world/us/crypto/commodities/forex) -> runs an offline scan that
    auto-sends a Telegram signal for qualifying picks;
  * "portfolio" -> forecasts your local holdings and warns on negative outlook.

Used by the GitHub Actions 24-7 job, or run manually:
    python -m scanner.signals
    python -m scanner.signals us crypto portfolio   # override markets
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass

from scanner.config import get_config
from scanner.kronos_client import KronosClient
from scanner.openalice_client import OpenAliceClient
from scanner.portfolio import PortfolioStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("scanner.signals")


@dataclass(frozen=True)
class RunSpec:
    directive: str
    asset_class: str
    label: str
    max_results: int | None = None

_MARKET_ASSET = {
    "etfs": "etf",
    "global-etfs": "etf",
    "crypto": "crypto",
    "commodities": "commodity",
    "commodity": "commodity",
    "futures": "commodity",
    "forex": "forex",
    "fx": "forex",
    "world": "index",
    "us": "index",
    "sp500": "index",
    "s&p500": "index",
    "nasdaq": "index",
    "dow": "index",
}

_GLOBAL_INDEX_ETFS = [
    "SPY", "QQQ", "DIA", "IWM",     # US
    "EWU", "FEZ", "EWG", "EWQ", "EWP", "EWI",  # UK + large Europe
    "EWJ", "MCHI", "FXI", "EWY", "EWT", "INDA",  # Japan/China/Korea/Taiwan/India
]

_COMMODITY_ETFS = [
    "GLD", "SLV", "USO", "UNG", "CPER", "PPLT", "PALL", "DBA", "CORN", "WEAT",
]

_TOP_FX = [
    "EURUSD=X", "GBPUSD=X", "USDJPY=X", "USDCHF=X", "USDCAD=X",
    "AUDUSD=X", "NZDUSD=X", "EURJPY=X", "GBPJPY=X", "EURGBP=X",
]

_TOP_CRYPTO = [
    "BTCUSD", "ETHUSD", "SOLUSD", "BNBUSD", "XRPUSD",
    "ADAUSD", "AVAXUSD", "DOTUSD", "LINKUSD", "DOGEUSD",
]

_SIGNAL_PROFILES = {
    "global-liquid": [
        RunSpec(" ".join(_GLOBAL_INDEX_ETFS), "etf", "global liquid index ETFs", 8),
        RunSpec(" ".join(_COMMODITY_ETFS), "etf", "liquid commodity ETFs", 6),
        RunSpec(" ".join(_TOP_FX), "forex", "top 10 FX pairs", 6),
        RunSpec(" ".join(_TOP_CRYPTO), "crypto", "top crypto majors", 6),
    ],
    "global": [
        RunSpec(" ".join(_GLOBAL_INDEX_ETFS), "etf", "global liquid index ETFs", 8),
        RunSpec(" ".join(_COMMODITY_ETFS), "etf", "liquid commodity ETFs", 6),
        RunSpec(" ".join(_TOP_FX), "forex", "top 10 FX pairs", 6),
        RunSpec(" ".join(_TOP_CRYPTO), "crypto", "top crypto majors", 6),
    ],
}


async def run_signals(markets: list[str]) -> None:
    import scanner.run as runmod
    for m in markets:
        m = m.strip().lower()
        if not m:
            continue
        if m == "portfolio":
            await portfolio_sell_check()
            continue
        if m in _SIGNAL_PROFILES:
            logger.info("Signal profile: %s (%d baskets)", m, len(_SIGNAL_PROFILES[m]))
            for spec in _SIGNAL_PROFILES[m]:
                await _run_spec(runmod, spec)
            continue
        ac = _MARKET_ASSET.get(m, "index")
        await _run_spec(runmod, RunSpec(m, ac, m))


async def _run_spec(runmod, spec: RunSpec) -> None:
    logger.info("Signal scan: %s assetclass=%s", spec.label, spec.asset_class)
    ns = argparse.Namespace(
        directive=spec.directive, asset_class=spec.asset_class, from_file=None,
        max_results=spec.max_results, provider=None, no_ui=True, push_inbox=False,
        stage_orders=False, pred_len=None, mc_paths=None, notify=False,
        no_notify=False, offline=True)
    try:
        path = await runmod.run_scan(ns)   # auto-notifies via the Telegram hook
        if path:
            from scanner import daily_board
            combined = daily_board.ingest(path, spec.label)
            logger.info("Daily board updated: %s", combined)
    except Exception as exc:  # noqa: BLE001
        logger.warning("signal scan %s failed: %s", spec.label, exc)


async def portfolio_sell_check() -> None:
    cfg = get_config()
    holdings = PortfolioStore().list()
    if not holdings:
        logger.info("Portfolio empty — nothing to check")
        return
    logger.info("Portfolio sell-check: %d holdings", len(holdings))

    kronos = KronosClient()
    await kronos.ensure_service_running()
    async with OpenAliceClient(cfg.openalice_mcp_url, offline=True) as oa:
        items = []
        for h in holdings:
            ohlcv = await oa.get_ohlcv(h["symbol"], bars=cfg.default_lookback)
            if ohlcv:
                items.append({"symbol": h["symbol"], "ohlcv": ohlcv})
        forecasts = await kronos.forecast_batch(items)
    if not cfg.kronos_is_remote:
        kronos.shutdown()

    sells = []
    for h in holdings:
        fc = forecasts.get(h["symbol"])
        if fc and (fc.get("expected_return_pct") or 0) < 0:
            sells.append((h, fc))

    # TA position-management alerts: trailing-stop breach or target reached.
    from scanner import entry_exit
    ohlcv_by = {it["symbol"]: it["ohlcv"] for it in items}
    ta_alerts = []
    for h in holdings:
        rows = ohlcv_by.get(h["symbol"])
        if not rows:
            continue
        ta = entry_exit.analyze(rows)
        price = rows[-1].get("close")
        ts, tgt = ta.get("trail_stop"), ta.get("target_value")
        if not isinstance(price, (int, float)):
            continue
        if isinstance(ts, (int, float)) and price <= ts:
            ta_alerts.append((h, f"trailing stop {ts:.2f} breached (px {price:.2f})"))
        elif isinstance(tgt, (int, float)) and price >= tgt:
            ta_alerts.append((h, f"target {tgt:.2f} reached (px {price:.2f}) — consider taking profit"))

    from scanner.notify import TelegramNotifier, _esc
    notifier = TelegramNotifier()
    if not sells and not ta_alerts:
        logger.info("Portfolio: no sell or position-level signals")
        return
    lines = ["⚠️ <b>VIGIL — portfolio alerts</b>", ""]
    if sells:
        lines.append("<b>Kronos sell signals</b>")
        for h, fc in sells:
            exp = fc.get("expected_return_pct")
            prob = fc.get("prob_up")
            prob_s = f" · P↑{prob*100:.0f}%" if isinstance(prob, (int, float)) else ""
            lines.append(f"<b>{_esc(h['symbol'])}</b> {exp:+.1f}%{prob_s}  (forecast negative)")
        lines.append("")
    if ta_alerts:
        lines.append("<b>Position levels</b>")
        for h, txt in ta_alerts:
            lines.append(f"<b>{_esc(h['symbol'])}</b> — {_esc(txt)}")
    msg = "\n".join(lines).strip()
    if notifier.enabled:
        await notifier.send(msg)
        logger.info("Portfolio alerts sent (%d sells, %d levels)", len(sells), len(ta_alerts))
    else:
        logger.info("Telegram not configured; would send:\n%s", msg)


def main() -> None:
    cfg = get_config()
    markets = sys.argv[1:] or cfg.signal_market_list
    logger.info("Vigil signals — markets: %s", markets)
    asyncio.run(run_signals(markets))


if __name__ == "__main__":
    main()
