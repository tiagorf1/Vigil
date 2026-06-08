"""Strategy equity-curve backtest — does the trade PLAN actually make money?

`backtest.py` measures whether the Kronos *forecast* is accurate. This measures
something different and just as important: whether the entry/stop/target plan
Vigil emits (from the TA engine in `entry_exit`) would have made money applied to
real history. It is a sequential, non-overlapping, intrabar-aware simulation:

  * At each step, compute the TA setup on data available THEN.
  * If there is a tradeable long setup, enter and walk forward bar by bar:
    stop hit -> exit at stop; target hit -> exit at target; neither within
    max_hold -> exit at the close. (Stop checked first within a bar = pessimistic.)
  * Compound non-overlapping trades into an equity curve.

Reports win rate, expectancy, profit factor, Sharpe, max drawdown, net of a
round-trip cost, broken out by setup type, next to buy-and-hold. No Kronos
service needed, so it runs instantly and offline.

    python -m scanner.strategy_backtest AAPL MSFT NVDA --max-hold 30
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
from datetime import datetime, timezone

from scanner.config import get_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("scanner.strategy_backtest")


def _simulate_trade(rows: list[dict], start: int, entry: float, stop: float,
                    target: float, max_hold: int) -> tuple[float, str, int]:
    """Walk forward from `start`. Return (gross_return, outcome, exit_idx)."""
    end = min(start + max_hold, len(rows) - 1)
    for j in range(start, end + 1):
        lo, hi, close = rows[j]["low"], rows[j]["high"], rows[j]["close"]
        if lo is not None and lo <= stop:                 # pessimistic: stop first
            return stop / entry - 1, "stop", j
        if hi is not None and hi >= target:
            return target / entry - 1, "target", j
    exit_close = rows[end]["close"]
    return exit_close / entry - 1, "time", end


def backtest_symbol(symbol: str, rows: list[dict], max_hold: int, step: int,
                    cost_bps: float, min_history: int) -> dict:
    from scanner import entry_exit
    trades: list[dict] = []
    i = min_history
    n = len(rows)
    cost = cost_bps / 10_000.0
    while i < n - 1:
        ta = entry_exit.analyze(rows[:i])
        ok = (ta.get("setup") and ta.get("entry_value") and ta.get("stop_value")
              and ta.get("target_value") and (ta.get("rr_value") or 0) > 0)
        if not ok:
            i += step
            continue
        entry = rows[i - 1]["close"]
        stop, target = ta["stop_value"], ta["target_value"]
        if not (stop < entry < target):     # only clean long setups
            i += step
            continue
        gross, outcome, exit_idx = _simulate_trade(rows, i, entry, stop, target, max_hold)
        net = gross - 2 * cost              # round-trip cost
        trades.append({
            "date": rows[i - 1].get("ts"), "setup": ta["setup"],
            "ret_pct": round(net * 100, 2), "outcome": outcome,
            "bars_held": exit_idx - i + 1, "confluence": ta.get("confluence"),
        })
        i = exit_idx + 1                    # non-overlapping
    return _summarize(symbol, rows, trades, max_hold, min_history)


def _summarize(symbol: str, rows: list[dict], trades: list[dict],
               max_hold: int, min_history: int) -> dict:
    if not trades:
        return {"symbol": symbol, "trades": 0, "note": "no setups triggered"}
    rets = [t["ret_pct"] / 100 for t in trades]
    equity = [1.0]
    for r in rets:
        equity.append(equity[-1] * (1 + r))
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    avg_hold = sum(t["bars_held"] for t in trades) / len(trades)

    # By-setup breakdown.
    by_setup: dict[str, dict] = {}
    for t in trades:
        b = by_setup.setdefault(t["setup"], {"n": 0, "wins": 0, "ret": 0.0})
        b["n"] += 1
        b["wins"] += 1 if t["ret_pct"] > 0 else 0
        b["ret"] += t["ret_pct"]
    for b in by_setup.values():
        b["win_rate"] = round(b["wins"] / b["n"], 3)
        b["avg_ret_pct"] = round(b["ret"] / b["n"], 2)

    bh = rows[-1]["close"] / rows[min_history - 1]["close"] - 1
    return {
        "symbol": symbol,
        "trades": len(trades),
        "win_rate": round(len(wins) / len(trades), 3),
        "expectancy_pct": round(sum(t["ret_pct"] for t in trades) / len(trades), 2),
        "total_return_pct": round((equity[-1] - 1) * 100, 2),
        "buy_hold_pct": round(bh * 100, 2),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 1e-9 else None,
        "sharpe": _sharpe(rets, avg_hold),
        "max_drawdown_pct": _max_dd(equity),
        "avg_bars_held": round(avg_hold, 1),
        "outcomes": {o: sum(1 for t in trades if t["outcome"] == o)
                     for o in ("target", "stop", "time")},
        "by_setup": by_setup,
        "trade_log": trades[-25:],
    }


def _sharpe(rets: list[float], avg_hold: float) -> float | None:
    if len(rets) < 2:
        return None
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))
    if sd < 1e-9 or avg_hold <= 0:
        return None
    trades_per_year = 252.0 / avg_hold
    return round(m / sd * math.sqrt(trades_per_year), 2)


def _max_dd(equity: list[float]) -> float:
    peak, mdd = equity[0], 0.0
    for v in equity:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return round(mdd * 100, 2)


def _aggregate(results: list[dict]) -> dict:
    ok = [r for r in results if r.get("trades")]
    if not ok:
        return {}
    tot_tr = sum(r["trades"] for r in ok)
    def wavg(key):
        vals = [(r[key], r["trades"]) for r in ok if isinstance(r.get(key), (int, float))]
        w = sum(n for _, n in vals)
        return round(sum(v * n for v, n in vals) / w, 3) if w else None
    return {
        "symbols": len(ok), "total_trades": tot_tr,
        "win_rate": wavg("win_rate"), "expectancy_pct": wavg("expectancy_pct"),
        "avg_total_return_pct": wavg("total_return_pct"),
        "avg_buy_hold_pct": wavg("buy_hold_pct"), "sharpe": wavg("sharpe"),
    }


async def run(symbols: list[str], max_hold: int, step: int, cost_bps: float,
              min_history: int, bars: int) -> dict:
    from scanner import market_data
    results = []
    for sym in symbols:
        rows = await market_data.fallback_ohlcv(sym, bars=bars)
        if not rows or len(rows) < min_history + max_hold + 5:
            results.append({"symbol": sym, "trades": 0, "note": "insufficient history"})
            continue
        res = backtest_symbol(sym, rows, max_hold, step, cost_bps, min_history)
        results.append(res)
        logger.info("%s: %d trades, win %s, strat %s%% vs B&H %s%%, Sharpe %s",
                    sym, res.get("trades"), res.get("win_rate"),
                    res.get("total_return_pct"), res.get("buy_hold_pct"), res.get("sharpe"))
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "params": {"max_hold": max_hold, "step": step, "cost_bps": cost_bps,
                   "min_history": min_history},
        "aggregate": _aggregate(results), "results": results,
    }
    outputs = get_config().project_root / "outputs"
    outputs.mkdir(exist_ok=True)
    import json
    (outputs / "strategy_backtest.json").write_text(json.dumps(out, indent=2, default=str))
    return out


def _print_summary(out: dict) -> None:
    agg = out.get("aggregate", {})
    print("\n=== Strategy backtest (TA entry/stop/target on history) ===")
    print(f"{agg.get('symbols', 0)} names · {agg.get('total_trades', 0)} trades · "
          f"max-hold {out['params']['max_hold']}d · cost {out['params']['cost_bps']}bps")
    print(f"  win rate        : {agg.get('win_rate')}")
    print(f"  expectancy/trade: {agg.get('expectancy_pct')}%")
    print(f"  strategy return : {agg.get('avg_total_return_pct')}%  "
          f"vs buy-hold {agg.get('avg_buy_hold_pct')}%")
    print(f"  Sharpe          : {agg.get('sharpe')}")
    print("  -> outputs/strategy_backtest.json\n")


def main(argv: list[str] | None = None) -> None:
    import sys
    p = argparse.ArgumentParser(prog="scanner.strategy_backtest")
    p.add_argument("symbols", nargs="+")
    p.add_argument("--max-hold", type=int, default=30, help="max bars to hold a trade")
    p.add_argument("--step", type=int, default=3, help="bars to advance when flat")
    p.add_argument("--cost-bps", type=float, default=5.0, help="round-trip cost in bps")
    p.add_argument("--min-history", type=int, default=220)
    p.add_argument("--bars", type=int, default=1200)
    args = p.parse_args(argv if argv is not None else sys.argv[1:])
    out = asyncio.run(run([s.upper() for s in args.symbols], args.max_hold, args.step,
                          args.cost_bps, args.min_history, args.bars))
    _print_summary(out)


if __name__ == "__main__":
    main()
