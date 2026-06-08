"""Intraday short-horizon forecasts — the day-trade mode.

The daily scan forecasts days-to-weeks ahead. This uses Yahoo's intraday bars
(1m/5m/15m) and runs the same Kronos engine for an intra-session view: the next
few hours of expected path, prob-up, and a vol cone. It is a separate mode on
purpose — intraday dynamics, costs, and noise differ from the daily swing setups
Vigil ranks, so this is a focused tool, not part of the watchlist.

    python -m scanner.intraday AAPL MSFT --interval 5m --steps 12
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from scanner.kronos_client import KronosClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("scanner.intraday")

_RANGE_FOR = {"1m": "5d", "2m": "5d", "5m": "1mo", "15m": "1mo", "30m": "1mo", "60m": "3mo"}


async def forecast(symbols: list[str], interval: str = "5m", steps: int = 12,
                   n_paths: int | None = None) -> dict:
    from scanner import yahoo
    rng = _RANGE_FOR.get(interval, "1mo")
    items = []
    for sym in symbols:
        bars = await yahoo.intraday(sym, interval=interval, rng=rng)
        if bars and len(bars) >= 64:
            items.append({"symbol": sym, "ohlcv": bars[-400:]})
        else:
            logger.warning("skip %s: only %d intraday bars", sym, len(bars or []))
    if not items:
        return {"interval": interval, "steps": steps, "results": {}}

    kronos = KronosClient()
    await kronos.ensure_service_running()
    fc = await kronos.forecast_batch(items, pred_len=steps, n_paths=n_paths)
    if not kronos.cfg.kronos_is_remote:
        kronos.shutdown()

    out = {}
    for sym, f in fc.items():
        out[sym] = {
            "expected_return_pct": f.get("expected_return_pct"),
            "prob_up": f.get("prob_up"),
            "terminal_vol_pct": f.get("terminal_vol_pct"),
            "ret_q05_pct": f.get("ret_q05_pct"),
            "ret_q95_pct": f.get("ret_q95_pct"),
            "current_close": f.get("current_close"),
        }
    return {"interval": interval, "steps": steps, "results": out}


def main(argv: list[str] | None = None) -> None:
    import sys
    p = argparse.ArgumentParser(prog="scanner.intraday")
    p.add_argument("symbols", nargs="+")
    p.add_argument("--interval", default="5m", choices=list(_RANGE_FOR))
    p.add_argument("--steps", type=int, default=12, help="bars ahead to forecast")
    p.add_argument("--paths", type=int, default=None)
    args = p.parse_args(argv if argv is not None else sys.argv[1:])
    out = asyncio.run(forecast([s.upper() for s in args.symbols], args.interval,
                               args.steps, args.paths))
    print(f"\n=== Intraday {args.interval} · {args.steps} bars ahead ===")
    for sym, r in out["results"].items():
        er = r.get("expected_return_pct"); pu = r.get("prob_up")
        er_s = f"{er:+.2f}%" if isinstance(er, (int, float)) else "n/a"
        pu_s = f"{pu*100:.0f}%" if isinstance(pu, (int, float)) else "n/a"
        print(f"  {sym:10} {er_s:>8}  P(up) {pu_s:>4}  "
              f"vol {r.get('terminal_vol_pct')}%  px {r.get('current_close')}")
    print()


if __name__ == "__main__":
    main()
