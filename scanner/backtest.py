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
    from kronos_service.predictor import KronosForecaster
    cfg = get_config()
    forecaster = KronosForecaster()

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
                realized = rows[ci - 1 + H]["close"]
                if not cur or not realized:
                    continue
                key = f"{s}#h{H}#c{k}"
                items.append({"symbol": key, "ohlcv": inp})
                meta.append((key, s, asset_class_of(s), H, cur, realized))
        if not items:
            continue
        logger.info("H=%d: %d forecasts", H, len(items))
        res = {r["symbol"]: r for r in forecaster.forecast_batch(items, pred_len=H, n_paths=paths)}
        for key, s, ac, H_, cur, realized in meta:
            r = res.get(key)
            if not r or r.get("error"):
                continue
            pred_ret = (r.get("expected_return_pct") or 0.0) / 100.0
            real_ret = realized / cur - 1.0
            lo = r["cone"]["q05"][-1]; hi = r["cone"]["q95"][-1]
            records[(ac, H_)].append({
                "symbol": s, "pred": pred_ret, "real": real_ret,
                "covered": bool(lo <= realized <= hi),
            })

    return _aggregate(records, cfg)


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
    (outdir / "forecast_calibration.json").write_text(json.dumps(res["calibration"], indent=2))

    print("\n=== Backtest scorecard ===")
    print(f"{'bucket':14} {'n':>4} {'bias%':>7} {'hitRaw':>7} {'hitDeb':>7} {'rankRho':>8} {'CIcov':>6} {'sigma%':>7}")
    for k, v in res["scorecard"].items():
        print(f"{k:14} {v['n']:>4} {v['bias_pct']:>7} {v['hit_rate_raw']:>7} "
              f"{v['hit_rate_debiased']:>7} {str(v['rank_corr']):>8} "
              f"{v['model_ci95_coverage']:>6} {v['residual_sigma_pct']:>7}")
    o = res["overall"]
    print(f"\nOVERALL n={o['n']} debiased hit-rate={o['hit_rate_debiased']} "
          f"model CI95 coverage={o['model_ci95_coverage']}")
    print("Wrote outputs/backtest.json and outputs/forecast_calibration.json")


if __name__ == "__main__":
    main()
