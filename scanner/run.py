"""Scanner CLI entry point.

Usage:
    python -m scanner.run "European banks"
    python -m scanner.run "semiconductor equipment" --max-results 5
    python -m scanner.run "" --asset-class crypto
    python -m scanner.run "AAPL MSFT NVDA"          # explicit symbol list
    python -m scanner.run --from-file symbols.txt
    python -m scanner.run "AAPL" --no-ui --provider none
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from scanner.config import ConfigError, get_config
from scanner.kronos_client import KronosClient, KronosServiceError
from scanner.openalice_client import OpenAliceClient
from scanner.output import WatchlistOutput
from scanner.report_generator import ReportGenerator
from scanner.screener import Screener
from scanner.universe import UniverseBuilder
from scanner.index_components import preset_etfs, sector_etfs_for_directive

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("scanner.run")

try:
    from rich.console import Console
    _console = Console()
    def _print(msg: str) -> None: _console.print(msg)
except Exception:  # noqa: BLE001
    def _print(msg: str) -> None: print(msg)

# Optional progress sink set by the control-panel server so the browser can
# stream the same stage lines the CLI prints.
STATUS_CALLBACK = None


def status(msg: str) -> None:
    _print(msg)
    if STATUS_CALLBACK is not None:
        try:
            STATUS_CALLBACK(msg)
        except Exception:  # noqa: BLE001
            pass


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="scanner", description="Investment opportunity scanner")
    p.add_argument("directive", nargs="?", default="",
                   help="sector / market / keyword, or a space-separated symbol list")
    p.add_argument("--asset-class", choices=["equity", "crypto", "index", "etf", "commodity", "forex"], default=None)
    p.add_argument("--from-file", default=None, help="file with one symbol per line")
    p.add_argument("--max-results", type=int, default=None, help="cap watchlist size")
    p.add_argument("--pred-len", type=int, default=None,
                   help="forecast horizon in daily candles, e.g. 20, 60, 120")
    p.add_argument("--mc-paths", type=int, default=None,
                   help="Monte-Carlo Kronos paths per symbol; higher is more stable but slower")
    p.add_argument("--provider", choices=["gemini", "anthropic", "none"], default=None,
                   help="override LLM_PROVIDER for this run")
    p.add_argument("--no-ui", action="store_true", help="do not launch the web UI")
    p.add_argument("--push-inbox", action="store_true",
                   help="push the watchlist to OpenAlice's Inbox when done")
    p.add_argument("--stage-orders", action="store_true",
                   help="stage (not execute) orders for conviction-4+ picks in OpenAlice")
    p.add_argument("--notify", action="store_true",
                   help="force a Telegram signal even below thresholds")
    p.add_argument("--no-notify", action="store_true",
                   help="suppress Telegram signals for this run")
    p.add_argument("--offline", action="store_true",
                   help="run without OpenAlice (free Yahoo data) — for indexes/crypto, CI, 24-7")
    return p.parse_args(argv)


async def preflight(offline: bool = False) -> None:
    cfg = get_config()
    # Abort condition 1: LLM provider must be usable.
    cfg.require_llm_ready()
    if offline:
        return  # OpenAlice not required in offline mode (Stooq data)
    # Abort condition 2: OpenAlice MCP reachable. Probe the port with a cheap
    # HTTP request first — a full MCP handshake against a dead port hangs and
    # surfaces noisy cancellation, whereas a TCP connect fails fast and clean.
    if not await _openalice_reachable(cfg.openalice_mcp_url):
        raise SystemExit(
            f"\nERROR: OpenAlice MCP not reachable at {cfg.openalice_mcp_url}\n"
            "  Start OpenAlice with `pnpm dev` and confirm the MCP port it prints,\n"
            "  then set OPENALICE_MCP_URL in .env to match.\n"
        )


async def _openalice_reachable(mcp_url: str, timeout: float = 5.0) -> bool:
    """True if something is listening at the MCP URL.

    Any HTTP response (even 4xx/405) means the server is up. Only a connection
    error / timeout counts as unreachable.
    """
    import httpx
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            await client.get(mcp_url)
        return True
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
        return False
    except httpx.HTTPError:
        # Got far enough to talk HTTP — server is up.
        return True


async def run_scan(args: argparse.Namespace) -> str | None:
    cfg = get_config()
    directive = args.directive.strip()
    pred_len = _positive_int(getattr(args, "pred_len", None), cfg.default_pred_len)
    mc_paths = _positive_int(getattr(args, "mc_paths", None), cfg.kronos_mc_paths)

    symbols_from_file: list[str] = []
    if args.from_file:
        with open(args.from_file) as fh:
            symbols_from_file = [ln.strip().upper() for ln in fh if ln.strip()]

    kronos = KronosClient()

    async with OpenAliceClient(cfg.openalice_mcp_url, offline=getattr(args, "offline", False)) as oa:
        # ── [1/6] Universe ────────────────────────────────────────────────
        if symbols_from_file:
            universe = symbols_from_file
            status(f"[1/6] Universe from file: {len(universe)} symbols")
        else:
            status(f"[1/6] Building universe for '{directive or 'broad sweep'}'...")
            universe = await UniverseBuilder(oa).build(directive, args.asset_class)
        if not universe:
            status("No symbols in universe. Stopping.")
            return None
        requested_asset_class = args.asset_class
        asset_class = args.asset_class or ("crypto" if _looks_crypto(universe) else "equity")
        benchmark_symbols: list[str] = []
        if requested_asset_class == "index":
            benchmark_symbols = _dedupe(preset_etfs(directive) + sector_etfs_for_directive(directive))
            asset_class = "equity"
            if benchmark_symbols:
                status("      Benchmark ETF(s): " + ", ".join(benchmark_symbols))

        # Portfolio context: OpenAlice positions + your local Vigil portfolio.
        from scanner.portfolio import PortfolioStore
        positions = await oa.get_positions()
        oa_syms = {p["symbol"] for p in positions}
        local_syms = PortfolioStore().symbols()
        for s in local_syms:
            if s not in oa_syms:
                positions.append({"symbol": s, "source": "vigil"})
        held = {p["symbol"] for p in positions}
        if positions:
            status(f"      Portfolio: {len(positions)} held "
                   f"({len(local_syms)} local + {len(oa_syms)} OpenAlice)")
        macro = await oa.get_macro(["DGS10", "DTWEXBGS", "CPIAUCSL"])

        # ── [2/6] + [3/6] Screens ─────────────────────────────────────────
        status(f"[2/6] Screening {len(universe)} candidates (fundamental + technical)...")
        survivors = await Screener(oa).screen(universe, asset_class)
        status(f"[3/6] Screen survivors: {len(survivors)} names")
        if not survivors:
            status("No survivors after screening. Stopping.")
            return None

        # Resolve real names + drop non-tradeable symbols (data quality).
        from scanner.names import resolve_many
        name_map = await resolve_many([c.symbol for c in survivors])
        cleaned = []
        for c in survivors:
            info = name_map.get(c.symbol, {})
            if info.get("valid") is False:
                logger.info("Dropping %s (not a tradeable instrument: %s)",
                            c.symbol, info.get("quote_type"))
                continue
            if not c.profile.get("companyName"):
                c.profile["companyName"] = info.get("name") or c.symbol
            if not c.sector and info.get("quote_type"):
                c.sector = info["quote_type"].title()
            cleaned.append(c)
        survivors = cleaned or survivors

        # ── [4/6] Kronos batched forecasts (reuse screener's OHLCV) ────────
        status(f"[4/6] Kronos forecasting {len(survivors)} names "
               f"(batched, {pred_len}d / {mc_paths} paths)...")
        warning = _local_load_warning(cfg, len(survivors), pred_len, mc_paths)
        if warning:
            status("      " + warning)
        try:
            await kronos.ensure_service_running()
        except KronosServiceError as exc:
            raise SystemExit(f"\nERROR: {exc}\n")

        forecasts = await kronos.forecast_batch(
            [{"symbol": c.symbol, "ohlcv": c.ohlcv} for c in survivors],
            pred_len=pred_len, n_paths=mc_paths)

        benchmark_forecasts: list[dict] = []
        if benchmark_symbols:
            bench_ohlcv = await _gather_ohlcv(oa, benchmark_symbols, cfg.default_lookback)
            bench_fc = await kronos.forecast_batch(
                [{"symbol": s, "ohlcv": bench_ohlcv.get(s, [])} for s in benchmark_symbols],
                pred_len=pred_len, n_paths=mc_paths)
            benchmark_forecasts = [
                {"symbol": sym, **fc} for sym, fc in bench_fc.items()
            ]

        # ── [5/6] Holdings review: forecast held names not already screened ─
        exits: list[dict] = []
        review_syms = [s for s in held if s not in {c.symbol for c in survivors}]
        if review_syms:
            status(f"      Holdings review: forecasting {len(review_syms)} held names...")
            held_ohlcv = await _gather_ohlcv(oa, review_syms, cfg.default_lookback)
            held_fc = await kronos.forecast_batch(
                [{"symbol": s, "ohlcv": held_ohlcv.get(s, [])} for s in review_syms],
                pred_len=pred_len, n_paths=mc_paths)
            all_held_fc = {**held_fc,
                           **{c.symbol: forecasts[c.symbol] for c in survivors
                              if c.symbol in held and c.symbol in forecasts}}
            for sym, fc in all_held_fc.items():
                if (fc.get("expected_return_pct") or 0) < 0:
                    exits.append({"symbol": sym,
                                  "expected_return_pct": fc.get("expected_return_pct"),
                                  "prob_up": fc.get("prob_up")})

        # ── [6/6] Reports (concurrent, with backoff in the generator) ──────
        status(f"[6/6] Generating reports ({cfg.llm_provider})...")
        generator = ReportGenerator()
        sem = asyncio.Semaphore(8)

        async def build_entry(cand):
            fc = forecasts.get(cand.symbol)
            news = await oa.get_news(cand.symbol, limit=5)
            earnings = await oa.get_earnings_calendar(cand.symbol) if asset_class == "equity" else {}
            earnings_soon = _earnings_in_window(earnings, pred_len)
            async with sem:
                report = await asyncio.to_thread(
                    generator.generate,
                    cand.symbol, cand.profile, cand.financials, cand.ratios,
                    cand.analyst_estimates, cand.insider_trading, cand.indicators,
                    news, fc or {}, cand.fund_score, cand.tech_score,
                )
            # Annotate tags with structural flags.
            tags = list(report.get("tags", []))
            if cand.symbol in held:
                tags.append("held")
            if earnings_soon:
                tags.append("earnings_in_window")
            if asset_class in {"crypto", "etf", "commodity", "forex"}:
                tags.append(asset_class)
            if cand.sector:
                tags.append(cand.sector.lower().replace(" ", "_"))
            report["tags"] = list(dict.fromkeys(tags))  # dedupe, keep order
            return {"report": report, "forecast": fc, "sector": cand.sector,
                    "indicators": cand.indicators,
                    "fund_score": cand.fund_score, "tech_score": cand.tech_score}

        entries = await asyncio.gather(*[build_entry(c) for c in survivors])

        # ── Assemble ───────────────────────────────────────────────────────
        out = WatchlistOutput()
        watchlist = out.build(
            entries, directive=directive, total_scanned=len(universe),
            total_screened=len(survivors), macro=macro, positions=positions,
            exits=exits, benchmarks=benchmark_forecasts)
        watchlist["forecast_config"] = {
            "pred_len": pred_len,
            "mc_paths": mc_paths,
            "lookback": cfg.default_lookback,
            "model": cfg.kronos_model,
        }
        if args.max_results:
            watchlist["watchlist"] = watchlist["watchlist"][: args.max_results]
        path = out.save(watchlist)
        status(f"Done. Watchlist: {len(watchlist['watchlist'])} names"
               + (f", {len(exits)} exit signals" if exits else "") + f" -> {path}")

        # ── Optional integration: push to Inbox / stage orders ─────────────
        if args.push_inbox:
            ok = await oa.push_inbox(
                title=f"Scanner: {directive or 'broad sweep'}",
                markdown=out.to_markdown(watchlist),
                payload={"output_path": path, "directive": directive})
            status("      Inbox push: " + ("ok" if ok else "failed"))
        if args.stage_orders:
            await _stage_orders(oa, watchlist)

    # ── Telegram signals ─────────────────────────────────────────────────
    if not args.no_notify:
        from scanner.notify import TelegramNotifier, build_signal_message
        notifier = TelegramNotifier()
        if notifier.enabled:
            msg = build_signal_message(watchlist)
            if msg and (args.notify or _has_signals(watchlist)):
                ok = await notifier.send(msg)
                status("      Telegram: " + ("signal sent" if ok else "send failed"))
            else:
                status("      Telegram: nothing cleared the signal bar")

    kronos.shutdown()
    return path


def _has_signals(watchlist: dict) -> bool:
    from scanner.config import get_config
    cfg = get_config()
    for it in watchlist.get("watchlist", []):
        conv = it.get("conviction", 0) or 0
        exp = it.get("expected_return_pct")
        if conv >= cfg.signal_min_conviction or (
                isinstance(exp, (int, float)) and abs(exp) >= cfg.signal_min_return):
            return True
    return bool(watchlist.get("exits"))


async def _stage_orders(oa: OpenAliceClient, watchlist: dict) -> None:
    """Stage (never execute) orders for top conviction-4+ picks."""
    staged = 0
    for item in watchlist.get("watchlist", []):
        if item.get("conviction", 0) < 4 or item.get("held"):
            continue
        price = item.get("current_close")
        if not price:
            continue
        res = await oa.stage_order(
            symbol=item["symbol"], side="buy", qty=0,  # qty=0 => sizing left to user
            entry=price, stop=None, target=None)
        if res:
            staged += 1
    status(f"      Staged {staged} orders for review in OpenAlice (none executed)")


def _earnings_in_window(earnings: dict, pred_len: int) -> bool:
    """True if the next earnings date falls within ~pred_len trading days."""
    if not isinstance(earnings, dict):
        return False
    from datetime import datetime, timedelta
    for k in ("nextEarningsDate", "next_earnings_date", "date", "earningsDate"):
        v = earnings.get(k)
        if not v:
            continue
        try:
            d = datetime.fromisoformat(str(v)[:19].replace("Z", ""))
        except ValueError:
            continue
        horizon = datetime.now() + timedelta(days=int(pred_len * 1.5))
        return datetime.now() <= d <= horizon
    return False


async def _gather_ohlcv(oa: OpenAliceClient, symbols: list[str], bars: int) -> dict[str, list]:
    async def fetch(sym):
        return sym, await oa.get_ohlcv(sym, interval="1d", bars=bars + 50)
    pairs = await asyncio.gather(*[fetch(s) for s in symbols])
    return dict(pairs)


def _looks_crypto(symbols: list[str]) -> bool:
    crypto = sum(1 for s in symbols if s.endswith(("USD", "USDT", "BTC")))
    return crypto > len(symbols) / 2


def _dedupe(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _positive_int(value, fallback: int) -> int:
    try:
        n = int(value)
        return n if n > 0 else fallback
    except (TypeError, ValueError):
        return fallback


def _local_load_warning(cfg, names: int, pred_len: int, mc_paths: int) -> str:
    """Warn before a local run enters heat/slowdown territory.

    This is intentionally heuristic: Kronos runtime depends on device, memory,
    model cache warmth, and OHLCV length. It still gives the user a useful guard
    rail before turning a Mac into an accidental long-running worker.
    """
    if cfg.kronos_is_remote:
        return ""
    load = names * pred_len * mc_paths
    normal = 30 * 60 * 12
    heavy = 30 * 90 * 24
    if load > heavy:
        return ("Heavy local forecast load. Remote worker strongly recommended "
                f"({names} names x {pred_len}d x {mc_paths} paths).")
    if load > normal:
        return ("Large local forecast load. Expect heat/slowdown; consider fewer "
                "survivors, fewer paths, or remote Kronos.")
    return ""


def _launch_ui(open_browser: bool = True) -> None:
    cfg = get_config()
    handler = partial(SimpleHTTPRequestHandler, directory=str(cfg.project_root))
    httpd = ThreadingHTTPServer(("127.0.0.1", cfg.ui_port), handler)
    url = f"http://127.0.0.1:{cfg.ui_port}/ui/index.html"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    status(f"UI: {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        threading.Event().wait()  # keep the server alive until Ctrl-C
    except KeyboardInterrupt:
        status("\nShutting down UI server.")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    # Per-run provider override.
    if args.provider:
        import os
        os.environ["LLM_PROVIDER"] = args.provider
        get_config.cache_clear()  # type: ignore[attr-defined]

    try:
        asyncio.run(preflight(offline=args.offline))
    except ConfigError as exc:
        raise SystemExit(f"\nERROR: {exc}\n")

    path = asyncio.run(run_scan(args))

    if path and not args.no_ui:
        _launch_ui(open_browser=True)


if __name__ == "__main__":
    main()
