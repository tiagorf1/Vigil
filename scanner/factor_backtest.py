"""Cross-sectional factor evaluation — Information Coefficient + decile spread.

For each documented factor, at every historical monthly rebalance we rank the
universe by the factor and measure how well that ranking predicts forward
returns. The Information Coefficient (mean rank-corr of factor vs forward return)
and its t-stat say whether the factor has real, usable signal in OUR universe.
No forecasting, no GPU — pure, instant, free. This is the honest test that turns
"documented edge" into "confirmed in our data" (or rejects it).

    python -m scanner.factor_backtest --horizon 21 --cuts 24
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections import defaultdict

import numpy as np

from scanner.factors import FACTORS, score_all
from scanner.market_data import fallback_ohlcv

logger = logging.getLogger("scanner.factor_backtest")

_DEFAULT = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "V", "JNJ", "WMT",
    "PG", "XOM", "CVX", "HD", "KO", "MRK", "ABBV", "BAC", "DIS", "CSCO", "INTC",
    "AMD", "QCOM", "CRM", "NFLX", "MCD", "NKE", "BA", "CAT", "UNH", "PFE", "LLY",
    "TSLA", "ORCL", "IBM", "GS", "PEP", "COST", "TXN", "HON", "AXP", "MS", "C",
    "T", "VZ", "WFC", "GE", "RTX", "LOW", "UPS",
]


def _rank(a: np.ndarray) -> np.ndarray:
    order = a.argsort()
    ranks = np.empty(len(a), float)
    ranks[order] = np.arange(len(a))
    return ranks


def _spearman(x, y) -> float | None:
    if len(x) < 4:
        return None
    rx, ry = _rank(np.asarray(x, float)), _rank(np.asarray(y, float))
    if rx.std() == 0 or ry.std() == 0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


async def run(symbols, horizon, cuts, step=21, lookback=300, bars=1300) -> dict:
    hist = {}
    for s in symbols:
        rows = await fallback_ohlcv(s, bars=bars)
        if len(rows) >= lookback + horizon + cuts * step + 5:
            hist[s] = rows
        else:
            logger.info("skip %s (%d candles)", s, len(rows))
    logger.info("Factor universe: %d symbols", len(hist))

    ics = defaultdict(list)            # factor -> [IC per cut]
    pooled = defaultdict(list)         # factor -> [(score, fwd_ret)] across all
    for k in range(cuts):
        per_factor = defaultdict(list)  # factor -> [(sym, score)]
        fwd = {}
        for s, rows in hist.items():
            n = len(rows)
            ci = n - horizon - k * step
            if ci - lookback < 0 or ci + horizon - 1 >= n or ci <= 0:
                continue
            cur, fut = rows[ci - 1]["close"], rows[ci - 1 + horizon]["close"]
            if not cur or not fut:
                continue
            fwd[s] = fut / cur - 1.0
            for name, sc in score_all(rows[:ci]).items():
                if sc is not None:
                    per_factor[name].append((s, sc))
        for name, pairs in per_factor.items():
            xs = [sc for sym, sc in pairs if sym in fwd]
            ys = [fwd[sym] for sym, sc in pairs if sym in fwd]
            ic = _spearman(xs, ys)
            if ic is not None:
                ics[name].append(ic)
            pooled[name].extend((sc, fwd[sym]) for sym, sc in pairs if sym in fwd)

    out = {}
    for name in FACTORS:
        icl = ics.get(name, [])
        if len(icl) < 3:
            continue
        arr = np.array(icl)
        mean_ic, std_ic = float(arr.mean()), float(arr.std()) or 1e-9
        tstat = mean_ic / std_ic * np.sqrt(len(arr))
        pl = pooled.get(name, [])
        spread = None
        if len(pl) >= 9:
            pls = sorted(pl, key=lambda z: z[0])
            t = max(1, len(pls) // 3)
            spread = float(np.mean([f for _, f in pls[-t:]]) - np.mean([f for _, f in pls[:t]]))
        out[name] = {
            "mean_ic": round(mean_ic, 4),
            "ic_tstat": round(float(tstat), 2),
            "ic_hit_rate": round(float((arr > 0).mean()), 2),
            "n_cuts": len(arr),
            "tercile_spread_pct": round(spread * 100, 3) if spread is not None else None,
            "desc": FACTORS[name][1],
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="scanner.factor_backtest")
    ap.add_argument("--symbols", nargs="*", default=_DEFAULT)
    ap.add_argument("--horizon", type=int, default=21)
    ap.add_argument("--cuts", type=int, default=24)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    res = asyncio.run(run(args.symbols, args.horizon, args.cuts))
    print(f"\n=== Factor IC  (horizon={args.horizon}d, {args.cuts} monthly cuts) ===")
    print(f"{'factor':15} {'meanIC':>7} {'t-stat':>7} {'IC>0':>5} {'tercSprd%':>9}  desc")
    for name, v in sorted(res.items(), key=lambda kv: -abs(kv[1]["ic_tstat"])):
        print(f"{name:15} {v['mean_ic']:>7.4f} {v['ic_tstat']:>7.2f} "
              f"{v['ic_hit_rate']*100:>4.0f}% {str(v['tercile_spread_pct']):>9}  {v['desc']}")
    print("\nUsable factor ≈ |t-stat| > 2 with a consistent IC sign. tercSprd = top-"
          "minus-bottom-third forward return (the long/short the factor implies).")


if __name__ == "__main__":
    main()
