"""Walk-forward backtest + forecast calibration generator.

Why this exists: a held-out check showed Kronos forecasts were systematically
bearish (predicted down while reality rose) and the "95% cone" contained the
truth far less than 95% of the time. You cannot trust a forecast you have not
measured. This module steps a cursor through history, forecasts, compares to what
actually happened, and reports honest metrics PER asset-class and horizon:

  * direction hit-rate (raw and after de-biasing)
  * bias  = mean(predicted - realized) return   (catches the systematic tilt)
  * MAE, and Spearman rank correlation (does the *ranking* work?)
  * model 95%-cone coverage (should be ~95%; we found it was not)

It then writes `outputs/forecast_calibration.json` — per (asset_class, horizon):
the bias to remove and the empirical error stdev to use as the *real* spread.
`scanner.forecast_calibration` applies these to every live forecast, so the
numbers shown to you are calibrated, not the model's overconfident raw output.

Run:
    python -m scanner.backtest                       # default liquid sample
    python -m scanner.backtest --symbols AAPL MSFT BTCUSD --horizons 10 20 --cuts 6
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np

from scanner.config import get_config
from scanner.market_data import fallback_ohlcv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("scanner.backtest")

DEFAULT_SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "XOM", "KO", "JPM", "JNJ", "WMT",   # equities
    "SPY", "QQQ",                                                # index ETFs
    "BTCUSD", "ETHUSD",                                          # crypto
    "GLD", "EURUSD=X",                                           # commodity, FX
]
MIN_SAMPLE_BACKED_N = 30


def asset_class_of(symbol: str) -> str:
    up = symbol.upper()
    if up.endswith("=X"):
        return "forex"
    if up.endswith("=F"):
        return "commodity"
    if up.startswith("^"):
        return "index"
    if up.endswith(("USD", "USDT")):
        return "crypto"
    if up in ("SPY", "QQQ", "DIA", "IWM", "GLD", "SLV", "USO"):
        return "etf"
    return "equity"


def _spearman(pred: list[float], real: list[float]) -> float | None:
    if len(pred) < 4:
        return None
    def rank(a):
        order = np.argsort(a)
        r = np.empty(len(a)); r[order] = np.arange(len(a))
        return r
    rp, rr = rank(np.array(pred)), rank(np.array(real))
    if rp.std() == 0 or rr.std() == 0:
        return None
    return float(np.corrcoef(rp, rr)[0, 1])


async def run_backtest(symbols, horizons, cuts, lookback, paths, bars=700) -> dict:
    cfg = get_config()
    # Forecaster routing: when a remote GPU box (KRONOS_SERVICE_URL) OR a RunPod
    # serverless endpoint is configured, run the whole backtest FROM HERE
    # (Mac/box) and offload only the heavy Kronos forecasting — no local torch,
    # no pod/terminal. Otherwise run Kronos in-process (the old local-CPU path).
    if cfg.kronos_is_remote or cfg.kronos_is_serverless:
        from scanner.kronos_client import KronosClient
        _kc = KronosClient()
        await _kc.ensure_service_running()
        logger.info("Backtest forecasting via %s",
                    "serverless GPU" if cfg.kronos_is_serverless else cfg.kronos_service_url)

        async def _forecast(items, H, n_paths):
            # client returns {symbol: forecast}; normalise to the list shape the
            # in-process predictor returns, so the caller is identical.
            return list((await _kc.forecast_batch(items, pred_len=H, n_paths=n_paths)).values())
    else:
        from kronos_service.predictor import KronosForecaster
        _forecaster = KronosForecaster()

        async def _forecast(items, H, n_paths):
            return _forecaster.forecast_batch(items, pred_len=H, n_paths=n_paths)

    # Load history once per symbol.
    hist = {}
    for s in symbols:
        rows = await fallback_ohlcv(s, bars=bars)
        if len(rows) >= lookback + max(horizons) + 5:
            hist[s] = rows
        else:
            logger.warning("skip %s: only %d candles", s, len(rows))
    logger.info("Backtest universe: %d symbols", len(hist))

    # records[(asset_class, horizon)] -> list of dicts
    records = defaultdict(list)

    from scanner import entry_exit

    for H in horizons:
        step = max(H, 5)
        items, meta = [], []
        for s, rows in hist.items():
            n = len(rows)
            for k in range(cuts):
                ci = n - H - k * step          # input ends at index ci (exclusive)
                if ci - lookback < 0 or ci + H - 1 >= n or ci <= 0:
                    continue
                inp = rows[:ci][-lookback:]
                cur = rows[ci - 1]["close"]
                future = rows[ci:ci + H]       # the H realized bars after entry
                realized = rows[ci - 1 + H]["close"]
                if not cur or not realized or len(future) < H:
                    continue
                key = f"{s}#h{H}#c{k}"
                items.append({"symbol": key, "ohlcv": inp})
                meta.append((key, s, asset_class_of(s), H, k, cur, realized, inp, future))
        if not items:
            continue
        logger.info("H=%d: %d forecasts", H, len(items))
        res = {r["symbol"]: r for r in await _forecast(items, H, paths)}
        for key, s, ac, H_, k, cur, realized, inp, future in meta:
            r = res.get(key)
            if not r or r.get("error"):
                continue
            pred_ret = (r.get("expected_return_pct") or 0.0) / 100.0
            real_ret = realized / cur - 1.0
            lo = r["cone"]["q05"][-1]; hi = r["cone"]["q95"][-1]
            # ── Strategy realised P&L (first-passage), not just point direction ──
            side = "long" if pred_ret >= 0 else "short"
            ta = entry_exit.analyze(inp, direction=side)
            R = _simulate_trade(ta, side, cur, future)
            agrees = (ta.get("trend") == "up" and side == "long") or \
                     (ta.get("trend") == "down" and side == "short")
            # ── naive baselines on the SAME cut (the bar Kronos must clear) ──
            naive_vol, naive_mom = _naive_signals(inp)
            naive_side = "long" if (naive_mom or 0.0) >= 0 else "short"
            naive_ta = entry_exit.analyze(inp, direction=naive_side)
            naive_R = _simulate_trade(naive_ta, naive_side, cur, future)
            records[(ac, H_)].append({
                "symbol": s, "cut": k, "pred": pred_ret, "real": real_ret,
                "covered": bool(lo <= realized <= hi),
                # predicted vs realised VOLATILITY (the pure-vol-play test)
                "pred_vol": (r.get("terminal_vol_pct") or 0.0) / 100.0,
                "real_vol": _realised_vol(cur, future),
                # strategy outcome + the conditions we want to slice on
                "R": R,
                "win": (R is not None and R > 0),
                "agrees": bool(agrees),
                "confluence": int(ta.get("confluence") or 0),
                "setup": ta.get("setup") or "none",
                # naive baselines for the head-to-head
                "naive_vol": naive_vol,
                "naive_mom": naive_mom,
                "naive_R": naive_R,
            })

    return _aggregate(records, cfg)


def _simulate_trade(ta: dict, side: str, entry: float, future: list[dict]) -> float | None:
    """First-passage R-multiple for the actual trade plan: walk the realised
    bars and see whether the STOP or the TARGET prints first. Conservative — a
    bar that straddles both is counted as the stop. Returns the realised reward
    in units of risk (R); None when there is no usable setup."""
    stop, target = ta.get("stop_value"), ta.get("target_value")
    if not (isinstance(stop, (int, float)) and isinstance(target, (int, float))):
        return None
    risk = abs(entry - stop)
    if risk <= 1e-9:
        return None
    for bar in future:
        hi, lo = bar.get("high"), bar.get("low")
        if hi is None or lo is None:
            continue
        if side == "long":
            if lo <= stop:
                return -1.0
            if hi >= target:
                return (target - entry) / risk
        else:
            if hi >= stop:
                return -1.0
            if lo <= target:
                return (entry - target) / risk
    fc = future[-1].get("close")
    if fc is None:
        return None
    return (fc - entry) / risk if side == "long" else (entry - fc) / risk


def _realised_vol(entry: float, future: list[dict]) -> float:
    """Stdev of daily returns along the realised path — direction-agnostic, for
    the predicted-vs-realised volatility ranking test."""
    closes = [entry] + [b.get("close") for b in future if b.get("close") is not None]
    if len(closes) < 3:
        return 0.0
    arr = np.array(closes, dtype=float)
    rets = np.diff(arr) / arr[:-1]
    return float(np.std(rets))


def _naive_signals(inp: list[dict], win: int = 20) -> tuple[float | None, float | None]:
    """Dumb baselines from the input window alone (no model):
    naive_vol = trailing realised vol; naive_mom = trailing `win`-day return.
    These are what Kronos must BEAT to justify its existence."""
    closes = [r.get("close") for r in inp if r.get("close") is not None]
    if len(closes) < win + 1:
        return None, None
    arr = np.array(closes[-(win + 1):], dtype=float)
    rets = np.diff(arr) / arr[:-1]
    return float(np.std(rets)), float(arr[-1] / arr[0] - 1.0)


def _bucket_stats(recs: list[dict]) -> dict:
    Rs = np.array([r["R"] for r in recs], dtype=float)
    return {"n": len(Rs), "expectancy_R": round(float(Rs.mean()), 3),
            "win_rate": round(float((Rs > 0).mean()), 3)}


def _strategy_summary(records: dict) -> dict:
    """Realised trade economics per (asset_class, horizon): expectancy in R,
    win rate, profit factor. This is what the system actually harvests."""
    out = {}
    for (ac, H), recs in sorted(records.items()):
        Rs = np.array([r["R"] for r in recs if r["R"] is not None], dtype=float)
        if len(Rs) < 5:
            continue
        wins, losses = Rs[Rs > 0], Rs[Rs <= 0]
        out[f"{ac}@{H}"] = {
            "n_trades": int(len(Rs)),
            "expectancy_R": round(float(Rs.mean()), 3),
            "win_rate": round(float((Rs > 0).mean()), 3),
            "avg_win_R": round(float(wins.mean()), 3) if len(wins) else None,
            "avg_loss_R": round(float(losses.mean()), 3) if len(losses) else None,
            "profit_factor": round(float(wins.sum() / abs(losses.sum())), 3)
                              if losses.sum() != 0 else None,
            "quality": "sample_backed" if len(Rs) >= MIN_SAMPLE_BACKED_N else "low_sample_report_only",
        }
    return out


def _conditional_summary(records: dict) -> dict:
    """Where the edge lives: expectancy sliced by trade condition, pooled per
    asset class across horizons. Tests whether filtered setups beat the average."""
    byac = defaultdict(list)
    for (ac, H), recs in records.items():
        byac[ac].extend(r for r in recs if r["R"] is not None)
    out = {}
    for ac, recs in sorted(byac.items()):
        buckets = {
            "all": recs,
            "agrees_trend": [r for r in recs if r["agrees"]],
            "fights_trend": [r for r in recs if not r["agrees"]],
            "confluence_ge3": [r for r in recs if r["confluence"] >= 3],
            "agree_and_conf3": [r for r in recs if r["agrees"] and r["confluence"] >= 3],
        }
        stats = {name: _bucket_stats(b) for name, b in buckets.items() if len(b) >= 5}
        if stats:
            out[ac] = stats
    return out


def _cross_sectional_summary(records: dict) -> dict:
    """Ranking skill: per cut, rank names by predicted return, measure the
    realised return spread between the top and bottom third. Works even if
    per-name direction is a coin flip."""
    out = {}
    for (ac, H), recs in sorted(records.items()):
        by_cut = defaultdict(list)
        for r in recs:
            by_cut[r["cut"]].append(r)
        spreads = []
        for _cut, rs in by_cut.items():
            if len(rs) < 6:
                continue
            rs_sorted = sorted(rs, key=lambda x: x["pred"])
            t = max(1, len(rs_sorted) // 3)
            bottom = rs_sorted[:t]
            top = rs_sorted[-t:]
            spreads.append(np.mean([x["real"] for x in top]) - np.mean([x["real"] for x in bottom]))
        if len(spreads) >= 2:
            out[f"{ac}@{H}"] = {
                "n_cuts": len(spreads),
                "mean_tercile_spread_pct": round(float(np.mean(spreads)) * 100, 3),
                "spread_hit_rate": round(float(np.mean([s > 0 for s in spreads])), 3),
            }
    return out


def _vol_skill_summary(records: dict) -> dict:
    """THE pure-vol test: does predicted terminal vol rank realised vol across
    names? A positive, stable rank correlation means Kronos finds the movers —
    the basis for volatility strategies even when direction is unpredictable."""
    out = {}
    for (ac, H), recs in sorted(records.items()):
        pv = [r["pred_vol"] for r in recs]
        rv = [r["real_vol"] for r in recs]
        if len(pv) < 8:
            continue
        rho = _spearman(pv, rv)
        out[f"{ac}@{H}"] = {
            "n": len(pv),
            "vol_rank_corr": round(rho, 3) if rho is not None else None,
            "quality": "sample_backed" if len(pv) >= MIN_SAMPLE_BACKED_N else "low_sample_report_only",
        }
    return out


def _baseline_summary(records: dict) -> dict:
    """The decisive test: does Kronos BEAT dumb baselines? Per (asset_class,
    horizon), compare Kronos vs naive on three axes:
      - vol ranking (predicted vs realised vol rank-corr)
      - direction hit-rate (sign of forecast vs sign of trailing momentum)
      - strategy expectancy (R from trading Kronos's side vs momentum's side)
    If Kronos doesn't clear the naive column, it isn't earning its keep."""
    out = {}
    for (ac, H), recs in sorted(records.items()):
        if len(recs) < 8:
            continue
        rv = [r["real_vol"] for r in recs]
        k_vol = _spearman([r["pred_vol"] for r in recs], rv)
        nv_pairs = [(r["naive_vol"], r["real_vol"]) for r in recs if r.get("naive_vol") is not None]
        n_vol = _spearman([a for a, _ in nv_pairs], [b for _, b in nv_pairs]) if len(nv_pairs) >= 8 else None
        k_dir = float(np.mean([(r["pred"] > 0) == (r["real"] > 0) for r in recs]))
        nm = [r for r in recs if r.get("naive_mom") is not None]
        n_dir = float(np.mean([(r["naive_mom"] >= 0) == (r["real"] > 0) for r in nm])) if nm else None
        kR = [r["R"] for r in recs if r.get("R") is not None]
        nR = [r["naive_R"] for r in recs if r.get("naive_R") is not None]
        out[f"{ac}@{H}"] = {
            "n": len(recs),
            "vol_rank_corr_kronos": round(k_vol, 3) if k_vol is not None else None,
            "vol_rank_corr_naive": round(n_vol, 3) if n_vol is not None else None,
            "dir_hit_kronos": round(k_dir, 3),
            "dir_hit_naive_mom": round(n_dir, 3) if n_dir is not None else None,
            "exp_R_kronos": round(float(np.mean(kR)), 3) if kR else None,
            "exp_R_naive_mom": round(float(np.mean(nR)), 3) if nR else None,
        }
    return out


def _aggregate(records: dict, cfg) -> dict:
    scorecard = {}
    calibration = {}
    overall = {"n": 0, "hit": 0, "covered": 0}
    z95 = 1.96

    for (ac, H), recs in sorted(records.items()):
        preds = [r["pred"] for r in recs]
        reals = [r["real"] for r in recs]
        n = len(recs)
        if n < 3:
            continue
        pred_arr = np.array(preds)
        real_arr = np.array(reals)
        errs = pred_arr - real_arr                         # model minus reality
        bias = float(errs.mean())
        sigma = float((real_arr - pred_arr).std())         # residual stdev
        mae = float(np.abs(errs).mean())
        hit_raw = float(np.mean([(p > 0) == (a > 0) for p, a in zip(preds, reals)]))
        hit_deb = float(np.mean([((p - bias) > 0) == (a > 0) for p, a in zip(preds, reals)]))
        cov = float(np.mean([r["covered"] for r in recs]))
        rho = _spearman(preds, reals)
        r2 = _r2(pred_arr, real_arr)
        shrink = _shrink_factor(r2, n)

        scorecard[f"{ac}@{H}"] = {
            "n": n,
            "quality": "sample_backed" if n >= MIN_SAMPLE_BACKED_N else "low_sample_report_only",
            "bias_pct": round(bias * 100, 2),
            "mae_pct": round(mae * 100, 2),
            "hit_rate_raw": round(hit_raw, 3),
            "hit_rate_debiased": round(hit_deb, 3),
            "rank_corr": round(rho, 3) if rho is not None else None,
            "r2": round(r2, 3) if r2 is not None else None,
            "shrink_factor": round(shrink, 3),
            "model_ci95_coverage": round(cov, 3),
            "residual_sigma_pct": round(sigma * 100, 2),
        }
        calibration.setdefault(ac, {})[str(H)] = {
            "add_pct": round(-bias * 100, 4),     # add to predicted return to de-bias
            "sigma_pct": round(sigma * 100, 4),   # true terminal stdev (for cone + prob)
            "shrink_factor": round(shrink, 4),     # pull overstated returns toward zero
            "r2": round(r2, 4) if r2 is not None else None,
            "ci95_halfwidth_pct": round(z95 * sigma * 100, 4),
            "n": n,
            "quality": "sample_backed" if n >= MIN_SAMPLE_BACKED_N else "low_sample_report_only",
        }
        overall["n"] += n
        overall["hit"] += hit_deb * n
        overall["covered"] += cov * n

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "settings": {"mc_paths_note": "see KRONOS_MC_PATHS/T/TOP_P", },
        "overall": {
            "n": overall["n"],
            "hit_rate_debiased": round(overall["hit"] / overall["n"], 3) if overall["n"] else None,
            "model_ci95_coverage": round(overall["covered"] / overall["n"], 3) if overall["n"] else None,
        },
        "scorecard": scorecard,
        # ── the honest backtest: does the SYSTEM make money, and where? ──
        "strategy": _strategy_summary(records),          # realised R-multiple economics
        "conditional": _conditional_summary(records),    # expectancy by trade condition
        "cross_sectional": _cross_sectional_summary(records),  # ranking skill (decile spread)
        "vol_skill": _vol_skill_summary(records),        # predicted-vs-realised vol ranking
        "baselines": _baseline_summary(records),          # Kronos vs naive vol/momentum
        "calibration": calibration,
    }
    return result


def _r2(pred: np.ndarray, real: np.ndarray) -> float | None:
    """Out-of-sample explanatory power proxy for return magnitudes."""
    if len(pred) < 4 or float(pred.std()) == 0.0 or float(real.std()) == 0.0:
        return None
    corr = float(np.corrcoef(pred, real)[0, 1])
    if not math.isfinite(corr) or corr <= 0:
        return 0.0
    return max(0.0, min(1.0, corr * corr))


def _shrink_factor(r2: float | None, n: int) -> float:
    """Convert weak historical magnitude skill into an honest return haircut.

    sqrt(R²) behaves like an absolute correlation. We then damp it for tiny
    samples so a small lucky backtest cannot authorize large headline returns.
    """
    if r2 is None:
        return 0.25
    sample_conf = n / (n + 30.0)
    raw = math.sqrt(max(0.0, min(1.0, r2))) * sample_conf
    return max(0.15, min(0.85, raw))


def main() -> None:
    ap = argparse.ArgumentParser(prog="scanner.backtest")
    ap.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS)
    ap.add_argument("--horizons", nargs="*", type=int, default=[10, 20])
    ap.add_argument("--cuts", type=int, default=5)
    ap.add_argument("--lookback", type=int, default=180)
    ap.add_argument("--paths", type=int, default=10)
    args = ap.parse_args()

    cfg = get_config()
    res = asyncio.run(run_backtest(args.symbols, args.horizons, args.cuts,
                                   args.lookback, args.paths))
    outdir = cfg.project_root / "outputs"; outdir.mkdir(exist_ok=True)
    (outdir / "backtest.json").write_text(json.dumps(res, indent=2))
    # Guard: only promote to the live calibration when the run is big enough to
    # be trustworthy — a tiny/test backtest must NOT clobber production calibration.
    _n = (res.get("overall") or {}).get("n", 0)
    if _n >= 100:
        (outdir / "forecast_calibration.json").write_text(json.dumps(res["calibration"], indent=2))
        print(f"Updated forecast_calibration.json (n={_n}).")
    else:
        print(f"Sample too small (n={_n}); kept existing forecast_calibration.json. "
              f"Re-run with more symbols/cuts to update calibration.")

    print("\n=== Backtest scorecard ===")
    print(f"{'bucket':14} {'n':>4} {'bias%':>7} {'hitRaw':>7} {'hitDeb':>7} {'rankRho':>8} {'CIcov':>6} {'sigma%':>7}")
    for k, v in res["scorecard"].items():
        print(f"{k:14} {v['n']:>4} {v['bias_pct']:>7} {v['hit_rate_raw']:>7} "
              f"{v['hit_rate_debiased']:>7} {str(v['rank_corr']):>8} "
              f"{v['model_ci95_coverage']:>6} {v['residual_sigma_pct']:>7}")
    o = res["overall"]
    print(f"\nOVERALL n={o['n']} debiased hit-rate={o['hit_rate_debiased']} "
          f"model CI95 coverage={o['model_ci95_coverage']}")

    print("\n=== Strategy economics (does the SYSTEM make money?) ===")
    print(f"{'bucket':14} {'trades':>6} {'exp_R':>6} {'win%':>6} {'PF':>6}")
    for k, v in res.get("strategy", {}).items():
        print(f"{k:14} {v['n_trades']:>6} {v['expectancy_R']:>6} "
              f"{v['win_rate']:>6} {str(v['profit_factor']):>6}")

    print("\n=== Where the edge lives (expectancy_R by condition) ===")
    for ac, buckets in res.get("conditional", {}).items():
        print(f"  {ac}:")
        for name, b in buckets.items():
            print(f"    {name:18} n={b['n']:>4} exp_R={b['expectancy_R']:>6} win%={b['win_rate']}")

    print("\n=== Ranking skill (top-minus-bottom tercile return) ===")
    for k, v in res.get("cross_sectional", {}).items():
        print(f"  {k:14} spread={v['mean_tercile_spread_pct']:>6}%  consistency={v['spread_hit_rate']}  (cuts={v['n_cuts']})")

    print("\n=== Pure-vol test (does predicted vol rank realised vol?) ===")
    for k, v in res.get("vol_skill", {}).items():
        print(f"  {k:14} vol_rank_corr={str(v['vol_rank_corr']):>7}  n={v['n']}  {v['quality']}")

    print("\n=== KRONOS vs NAIVE — does the model earn its keep? ===")
    print(f"{'bucket':12} {'volK':>6} {'volN':>6}  | {'dirK':>5} {'dirN':>5}  | {'expRK':>6} {'expRN':>6}")
    for k, v in res.get("baselines", {}).items():
        def _s(x): return f"{x:.3f}" if isinstance(x, (int, float)) else "  -  "
        print(f"{k:12} {_s(v['vol_rank_corr_kronos']):>6} {_s(v['vol_rank_corr_naive']):>6}  | "
              f"{_s(v['dir_hit_kronos']):>5} {_s(v['dir_hit_naive_mom']):>5}  | "
              f"{_s(v['exp_R_kronos']):>6} {_s(v['exp_R_naive_mom']):>6}")
    print("  (volK>volN => Kronos predicts vol CHANGES, not just levels;")
    print("   dirK/expRK > naive => Kronos direction beats plain momentum)")

    print("\nWrote outputs/backtest.json and outputs/forecast_calibration.json")


if __name__ == "__main__":
    main()
