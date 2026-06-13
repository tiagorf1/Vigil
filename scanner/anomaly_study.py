"""Volatility-age anomaly studies — aimed at OUTSIZED moves, not tired premia.

Pure local OHLC math, no model, no GPU. Two hypotheses:

  1. Overnight-drift: does equity return accrue OVERNIGHT (buy close / sell open)
     rather than intraday (buy open / sell close)? A persistent, mechanical,
     barely-traded structural edge.
  2. Vol-compression -> outsized move: after realised vol hits a multi-month low
     (a "squeeze"), is the forward move MAGNITUDE bigger than normal? The
     coiled-spring detector — a "big move imminent" flag to pair with a trigger.

    python -m scanner.anomaly_study --horizon 10
"""

from __future__ import annotations

import argparse
import asyncio
import logging

import numpy as np

from scanner.factor_backtest import _DEFAULT
from scanner.market_data import fallback_ohlcv

logger = logging.getLogger("scanner.anomaly_study")


def _ann_sharpe(rets: np.ndarray) -> float:
    s = float(rets.std())
    return float(rets.mean() / s * np.sqrt(252)) if s > 0 else 0.0


def overnight_vs_intraday(hist: dict) -> dict:
    """Pool overnight (open/prev_close) vs intraday (close/open) returns."""
    on, intra = [], []
    for rows in hist.values():
        o = np.array([r.get("open") for r in rows], float)
        c = np.array([r.get("close") for r in rows], float)
        if len(c) < 30:
            continue
        on.append(o[1:] / c[:-1] - 1.0)
        intra.append(c / o - 1.0)
    on = np.concatenate(on); intra = np.concatenate(intra)
    on = on[np.isfinite(on)]; intra = intra[np.isfinite(intra)]
    return {
        "overnight_mean_bps": round(float(on.mean()) * 1e4, 2),
        "overnight_sharpe": round(_ann_sharpe(on), 2),
        "intraday_mean_bps": round(float(intra.mean()) * 1e4, 2),
        "intraday_sharpe": round(_ann_sharpe(intra), 2),
        "n_days": int(len(on)),
    }


def vol_squeeze_study(hist: dict, horizon: int, win: int = 20, lookback: int = 252) -> dict:
    """After a vol squeeze (20d vol in bottom decile of its trailing year),
    is the forward |return| over `horizon` bigger than the unconditional baseline?"""
    sq_moves, base_moves = [], []
    for rows in hist.values():
        c = np.array([r.get("close") for r in rows], float)
        if len(c) < lookback + horizon + win + 5:
            continue
        rets = np.diff(c) / c[:-1]
        rvol = np.array([rets[i - win:i].std() for i in range(win, len(rets))])
        base_idx = win  # offset of rvol[0] into c
        for j in range(lookback, len(rvol) - horizon):
            ci = base_idx + j + 1
            if ci + horizon >= len(c):
                continue
            fwd_abs = abs(c[ci + horizon] / c[ci] - 1.0)
            base_moves.append(fwd_abs)
            thresh = np.percentile(rvol[j - lookback:j], 10)
            if rvol[j] <= thresh:
                sq_moves.append(fwd_abs)
    if not sq_moves or not base_moves:
        return {}
    sq, base = np.array(sq_moves), np.array(base_moves)
    return {
        "squeeze_fwd_abs_move_pct": round(float(sq.mean()) * 100, 3),
        "baseline_fwd_abs_move_pct": round(float(base.mean()) * 100, 3),
        "ratio": round(float(sq.mean() / base.mean()), 3) if base.mean() else None,
        "n_squeezes": int(len(sq)),
    }


async def run(symbols, horizon) -> dict:
    hist = {}
    for s in symbols:
        rows = await fallback_ohlcv(s, bars=1300)
        if len(rows) >= 400:
            hist[s] = rows
    logger.info("Anomaly universe: %d symbols", len(hist))
    return {
        "overnight_vs_intraday": overnight_vs_intraday(hist),
        "vol_squeeze": vol_squeeze_study(hist, horizon),
    }


def main() -> None:
    ap = argparse.ArgumentParser(prog="scanner.anomaly_study")
    ap.add_argument("--symbols", nargs="*", default=_DEFAULT)
    ap.add_argument("--horizon", type=int, default=10)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    res = asyncio.run(run(args.symbols, args.horizon))
    o = res["overnight_vs_intraday"]
    print("\n=== Overnight-drift anomaly ===")
    print(f"  overnight: {o['overnight_mean_bps']:>6} bps/day  Sharpe {o['overnight_sharpe']}")
    print(f"  intraday:  {o['intraday_mean_bps']:>6} bps/day  Sharpe {o['intraday_sharpe']}")
    print(f"  (overnight >> intraday => buy-close/sell-open edge; n={o['n_days']} days)")
    v = res["vol_squeeze"]
    print("\n=== Vol-compression -> outsized move ===")
    if v:
        print(f"  forward |move| after squeeze: {v['squeeze_fwd_abs_move_pct']}%  vs  "
              f"baseline {v['baseline_fwd_abs_move_pct']}%   ratio {v['ratio']}  (n={v['n_squeezes']})")
        print("  (ratio>1 => squeezes precede BIGGER moves; pair with a direction trigger)")


if __name__ == "__main__":
    main()
