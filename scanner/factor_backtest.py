"""Cross-sectional factor lab — honest, cost-aware, multiple-testing-controlled.

For each documented factor, at every monthly rebalance we rank the universe and
measure (a) the Information Coefficient and (b) the **long-only net alpha** —
the forward return of the top tercile minus the universe mean, *after costs and
turnover* (we can't short, so the long leg is what's tradeable). Inference uses
Newey–West (overlapping returns are autocorrelated), a Benjamini–Hochberg FDR
haircut across the factors tested, and a reserved recent-months **holdout** that
gets one look. This is the gate that turns "documented edge" into "confirmed,
tradeable in our account" — or rejects it.

    python -m scanner.factor_backtest --horizon 21 --cuts 48 --cost-bps 40 --holdout 18
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
from collections import defaultdict

import numpy as np

from scanner import labstats
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
    """Collect, per factor and per monthly cut: the IC, the top-tercile long-only
    excess return, and the top-tercile membership (for turnover). cut k=0 is the
    most recent rebalance; larger k is older."""
    hist = {}
    for s in symbols:
        rows = await fallback_ohlcv(s, bars=bars)
        if len(rows) >= lookback + horizon + cuts * step + 5:
            hist[s] = rows
        else:
            logger.info("skip %s (%d candles)", s, len(rows))
    logger.info("Factor universe: %d symbols", len(hist))

    ic = defaultdict(dict)        # factor -> {cut_k: ic}
    excess = defaultdict(dict)    # factor -> {cut_k: top-tercile fwd minus universe mean}
    members = defaultdict(dict)   # factor -> {cut_k: frozenset(top-tercile symbols)}
    ls = defaultdict(dict)        # factor -> {cut_k: top-tercile minus bottom-tercile (long/short)}
    bottom = defaultdict(dict)    # factor -> {cut_k: frozenset(bottom-tercile symbols)}
    for k in range(cuts):
        per_factor = defaultdict(list)
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
        if len(fwd) < 9:
            continue
        univ_mean = float(np.mean(list(fwd.values())))
        for name, pairs in per_factor.items():
            pairs = [(s, sc) for s, sc in pairs if s in fwd]
            if len(pairs) < 9:
                continue
            xs = [sc for _, sc in pairs]
            ys = [fwd[s] for s, _ in pairs]
            r = _spearman(xs, ys)
            if r is not None:
                ic[name][k] = r
            ranked = sorted(pairs, key=lambda z: z[1])
            t = max(1, len(ranked) // 3)
            top, bot = ranked[-t:], ranked[:t]
            top_mean = float(np.mean([fwd[s] for s, _ in top]))
            bot_mean = float(np.mean([fwd[s] for s, _ in bot]))
            excess[name][k] = top_mean - univ_mean
            ls[name][k] = top_mean - bot_mean
            members[name][k] = frozenset(s for s, _ in top)
            bottom[name][k] = frozenset(s for s, _ in bot)
    return {"ic": ic, "excess": excess, "members": members, "ls": ls, "bottom": bottom}


def _turnover(ks, mem):
    ks = sorted(ks)
    ts = []
    for a, b in zip(ks, ks[1:]):
        A, B = mem.get(a), mem.get(b)
        if A and B:
            ts.append(len(A ^ B) / (2 * max(len(A), 1)))
    return float(np.mean(ts)) if ts else 0.0


def _factor_stats(name, ic, excess, members, ls, bottom, cost_bps, holdout,
                  horizon, cfd_annual) -> dict | None:
    cuts_sorted = sorted(excess.keys())          # ascending k (0 recent -> old)
    if len(cuts_sorted) < holdout + 6:
        holdout = max(0, len(cuts_sorted) // 4)   # adapt if short
    hold_k = set(cuts_sorted[:holdout])           # most-recent = holdout
    is_k = [k for k in cuts_sorted if k not in hold_k]

    cost = cost_bps / 1e4
    # CFD overnight financing on the short leg, charged over the hold (trading days).
    short_fin = (cfd_annual / 100.0) * (horizon / 252.0)

    def net_long(ks):
        drag = _turnover(ks, members) * cost          # long leg (Invest, no financing)
        return [excess[k] - drag for k in ks if k in excess]

    def net_ls(ks):
        drag = (_turnover(ks, members) + _turnover(ks, bottom)) * cost + short_fin
        return [ls[k] - drag for k in ks if k in ls]

    is_ic = [ic[k] for k in is_k if k in ic]
    if len(is_ic) < 6:
        return None
    ic_t, _ = labstats.newey_west_tstat(is_ic)
    net_is = net_long(is_k)
    gross_is = [excess[k] for k in is_k if k in excess]
    net_t, _ = labstats.newey_west_tstat(net_is)
    net_arr = np.asarray(net_is, float)
    sr = float(net_arr.mean() / net_arr.std()) if net_arr.std() > 0 else 0.0
    ls_is = net_ls(is_k)
    ls_t, _ = labstats.newey_west_tstat(ls_is)
    return {
        "n_is": len(is_k), "n_holdout": len(hold_k),
        "mean_ic": round(float(np.mean(is_ic)), 4),
        "ic_tstat_nw": round(ic_t, 2),
        "gross_excess_pct": round(float(np.mean(gross_is)) * 100, 3) if gross_is else None,
        "net_excess_pct": round(float(net_arr.mean()) * 100, 3),
        "net_tstat_nw": round(net_t, 2),
        "net_p": labstats.two_sided_p(net_t, len(net_is)),
        "ls_net_pct": round(float(np.mean(ls_is)) * 100, 3) if ls_is else None,
        "ls_net_tstat_nw": round(ls_t, 2),
        "turnover_pct": round(_turnover(is_k, members) * 100, 1),
        "sharpe_per_reb": round(sr, 2),
        "holdout_net_excess_pct": round(float(np.mean(net_long(sorted(hold_k)))) * 100, 3)
        if hold_k else None,
        "desc": FACTORS[name][1],
    }


def aggregate(raw, cost_bps, holdout, horizon, cfd_annual, fdr_q=0.10) -> dict:
    out = {}
    for name in FACTORS:
        st = _factor_stats(name, raw["ic"].get(name, {}), raw["excess"].get(name, {}),
                           raw["members"].get(name, {}), raw["ls"].get(name, {}),
                           raw["bottom"].get(name, {}), cost_bps, holdout, horizon, cfd_annual)
        if st:
            out[name] = st
    # FDR across the factors tested (on the in-sample net-alpha p-values)
    names = list(out)
    bh = labstats.benjamini_hochberg([out[n]["net_p"] for n in names], q=fdr_q)
    for i, n in enumerate(names):
        out[n]["fdr_pass"] = bool(bh["passed"][i])
    # deflated Sharpe: best Sharpe across the N factors tried
    if names:
        n_obs = max(out[n]["n_is"] for n in names)
        for n in names:
            out[n]["deflated_sharpe_p"] = round(
                labstats.deflated_sharpe(out[n]["sharpe_per_reb"], n_obs, len(names)), 3)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="scanner.factor_backtest")
    ap.add_argument("--symbols", nargs="*", default=_DEFAULT)
    ap.add_argument("--horizon", type=int, default=21)
    ap.add_argument("--cuts", type=int, default=48)
    ap.add_argument("--cost-bps", type=float, default=40.0,
                    help="round-trip cost in bps (T212 small/mid ~40-60)")
    ap.add_argument("--holdout", type=int, default=18, help="recent cuts reserved as holdout")
    ap.add_argument("--cfd-annual-pct", type=float, default=7.0,
                    help="CFD overnight financing, annual %% on the short leg")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    raw = asyncio.run(run(args.symbols, args.horizon, args.cuts))
    res = aggregate(raw, args.cost_bps, args.holdout, args.horizon, args.cfd_annual_pct)
    print(f"\n=== Factor lab  (horizon={args.horizon}d, {args.cuts} cuts, "
          f"cost={args.cost_bps:.0f}bps, CFD fin={args.cfd_annual_pct:.0f}%/yr, holdout={args.holdout}) ===")
    print(f"{'factor':15} {'IC':>7} {'IC_t':>6} {'Lnet%':>6} {'Lnet_t':>6} {'LSnet%':>6} {'LSnet_t':>7} "
          f"{'turn%':>6} {'FDR':>4} {'hold%':>6}  desc")
    for name, v in sorted(res.items(), key=lambda kv: -abs(kv[1]["net_tstat_nw"])):
        def s(x): return f"{x:.3f}" if isinstance(x, (int, float)) else "  -  "
        print(f"{name:15} {s(v['mean_ic']):>7} {s(v['ic_tstat_nw']):>6} "
              f"{s(v['net_excess_pct']):>6} {s(v['net_tstat_nw']):>6} {s(v['ls_net_pct']):>6} "
              f"{s(v['ls_net_tstat_nw']):>7} {s(v['turnover_pct']):>6} {'Y' if v['fdr_pass'] else 'n':>4} "
              f"{s(v['holdout_net_excess_pct']):>6}  {v['desc']}")
    print("\nLnet = long-only top-tercile minus universe, net of cost (T212 Invest).")
    print("LSnet = long top / short bottom, net of cost + CFD short financing.")
    print("Gate: positive net with t(NW) clearing FDR, AND surviving the holdout.")


if __name__ == "__main__":
    main()
