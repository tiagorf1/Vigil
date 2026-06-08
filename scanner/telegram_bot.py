"""Interactive Telegram command bot — run scans from your phone, on the cloud.

Run this on your always-on cloud box (Oracle Free / VPS / Modal). It long-polls
Telegram and, on a command from YOUR chat id, runs the scan on that box and
replies with the signal. This is the "cloud processing -> phone" loop: the heavy,
most-accurate compute happens off your Mac; you just text it.

Commands:
    /scan us            run a market scan (us | world | crypto | commodities | forex | global-liquid)
    /deep AAPL MSFT     deep scan specific tickers
    /portfolio          forecast your holdings + sell-check
    /signals            run your configured SIGNAL_MARKETS
    /status             show config (provider, kronos, markets)
    /help

Run:  python -m scanner.telegram_bot
Only messages from TELEGRAM_CHAT_ID are honored.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from scanner.config import get_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("scanner.telegram_bot")

HELP = ("Vigil bot commands:\n"
        "/scan <market>  - us | world | crypto | commodities | forex | global-liquid\n"
        "/deep <tickers> - e.g. /deep AAPL MSFT NVDA\n"
        "/portfolio      - forecast holdings + sell-check\n"
        "/signals        - run configured SIGNAL_MARKETS\n"
        "/status         - show config\n"
        "/help")


async def _api(cfg, method: str, payload: dict):
    url = f"https://api.telegram.org/bot{cfg.telegram_bot_token}/{method}"
    async with httpx.AsyncClient(timeout=70) as c:
        r = await c.post(url, json=payload)
        return r.json() if r.status_code == 200 else {}


async def _send(cfg, chat_id, text: str):
    # Telegram caps messages ~4096 chars.
    await _api(cfg, "sendMessage", {"chat_id": chat_id, "text": text[:4000],
                                    "parse_mode": "HTML", "disable_web_page_preview": True})


async def _handle(cfg, chat_id, text: str):
    import argparse
    import scanner.run as runmod
    from scanner.signals import run_signals, portfolio_sell_check
    from scanner.notify import build_signal_message
    from scanner.output import WatchlistOutput  # noqa: F401  (run_scan saves latest)

    parts = text.strip().split()
    cmd = parts[0].lower().lstrip("/")
    args = parts[1:]

    if cmd in ("help", "start"):
        await _send(cfg, chat_id, HELP); return
    if cmd == "status":
        await _send(cfg, chat_id,
                    f"provider={cfg.llm_provider}\nkronos={cfg.kronos_service_url}"
                    f"\nmarkets={cfg.signal_markets}\nmc_paths={cfg.kronos_mc_paths}")
        return
    if cmd == "portfolio":
        await _send(cfg, chat_id, "Forecasting your portfolio…")
        await portfolio_sell_check(); return
    if cmd == "signals":
        await _send(cfg, chat_id, f"Running signals: {cfg.signal_markets}…")
        await run_signals(cfg.signal_market_list); return
    if cmd == "scan":
        market = (args[0].lower() if args else "us")
        await _send(cfg, chat_id, f"Scanning {market}… (sends a signal if anything clears the bar)")
        await run_signals([market]); return
    if cmd == "deep":
        if not args:
            await _send(cfg, chat_id, "Usage: /deep AAPL MSFT"); return
        directive = " ".join(a.upper() for a in args)
        await _send(cfg, chat_id, f"Deep scan: {directive}…")
        ns = argparse.Namespace(
            directive=directive, asset_class=None, from_file=None, max_results=None,
            provider=None, no_ui=True, push_inbox=False, stage_orders=False,
            pred_len=None, mc_paths=None, notify=True, no_notify=False, offline=True)
        import json
        path = await runmod.run_scan(ns)
        try:
            wl = json.loads(open(path).read()) if path else {}
            msg = build_signal_message(wl) or "Scan done; nothing cleared the signal bar."
        except Exception:  # noqa: BLE001
            msg = "Scan done."
        await _send(cfg, chat_id, msg); return
    await _send(cfg, chat_id, "Unknown command. " + HELP)


async def serve() -> None:
    cfg = get_config()
    if not cfg.telegram_enabled:
        raise SystemExit("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set in .env")
    owner = str(cfg.telegram_chat_id)
    logger.info("Vigil Telegram bot polling (owner chat %s)", owner)
    await _send(cfg, owner, "Vigil bot online. " + HELP)
    offset = None
    while True:
        try:
            payload = {"timeout": 60}
            if offset is not None:
                payload["offset"] = offset
            data = await _api(cfg, "getUpdates", payload)
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or upd.get("edited_message") or {}
                chat_id = str((msg.get("chat") or {}).get("id", ""))
                text = msg.get("text") or ""
                if not text:
                    continue
                if chat_id != owner:
                    logger.warning("ignoring message from non-owner chat %s", chat_id)
                    continue
                try:
                    await _handle(cfg, chat_id, text)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("command failed")
                    await _send(cfg, chat_id, f"Error: {exc}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("poll error: %s", exc)
            await asyncio.sleep(5)


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
