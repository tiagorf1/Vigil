"""Kronos inference wrapper — batched and probabilistic.

Two upgrades over a naive point forecast:

* Batched inference via Kronos's `predict_batch`, so N symbols forecast in one
  GPU pass instead of N sequential calls.
* A Monte-Carlo cloud: each symbol is replicated `n_paths` times in the batch.
  Because sampling is stochastic (T>0, top_p<1) the copies diverge, giving an
  empirical distribution. From it we derive P(up), a quantile cone, and a
  forward-volatility estimate the strategy layer uses to size stops.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from scanner.config import get_config

logger = logging.getLogger("kronos_service.predictor")

_PRICE_COLS = ["open", "high", "low", "close"]
_MIN_HISTORY = 30
_MAX_SERIES_PER_CALL = 48  # chunk size for predict_batch (memory safety)


def _ensure_kronos_on_path(repo_path: str) -> None:
    repo = Path(repo_path)
    if not (repo / "model" / "kronos.py").exists():
        raise RuntimeError(
            f"Kronos source not found at {repo}. Clone it "
            "(git clone https://github.com/shiyu-coder/Kronos) and set "
            "KRONOS_REPO_PATH in .env."
        )
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))


class KronosForecaster:
    """Holds the warm model in memory. Construct once at service startup."""

    def __init__(self) -> None:
        self.cfg = get_config()
        _ensure_kronos_on_path(self.cfg.kronos_repo_path)
        from model import Kronos, KronosTokenizer, KronosPredictor  # noqa: E402

        device = None if self.cfg.kronos_device == "auto" else self.cfg.kronos_device
        t0 = time.time()
        logger.info("Loading tokenizer %s", self.cfg.kronos_tokenizer)
        tokenizer = KronosTokenizer.from_pretrained(self.cfg.kronos_tokenizer)
        logger.info("Loading model %s", self.cfg.kronos_model)
        model = Kronos.from_pretrained(self.cfg.kronos_model)
        self.predictor = KronosPredictor(model, tokenizer, device=device, max_context=512)
        self.device = str(self.predictor.device)
        n_params = sum(p.numel() for p in model.parameters())
        logger.info("Kronos ready on %s — %s (%.1fM params) in %.1fs",
                    self.device, self.cfg.kronos_model, n_params / 1e6, time.time() - t0)

    # ── public API ────────────────────────────────────────────────────────
    def forecast(self, symbol, ohlcv, pred_len=None, sample_count=None, n_paths=None) -> dict:
        out = self.forecast_batch([{"symbol": symbol, "ohlcv": ohlcv}],
                                  pred_len=pred_len, n_paths=n_paths)
        result = out[0]
        if result.get("error"):
            raise ValueError(result["error"])
        return result

    def forecast_batch(self, items: list[dict], pred_len=None, n_paths=None) -> list[dict]:
        pred_len = pred_len or self.cfg.default_pred_len
        n_paths = n_paths or self.cfg.kronos_mc_paths

        # Prepare valid frames; remember failures to return in order.
        prepared: list[dict] = []
        results: dict[int, dict] = {}
        for idx, item in enumerate(items):
            try:
                df = self._to_frame(item["ohlcv"])
                if len(df) < _MIN_HISTORY:
                    results[idx] = {"symbol": item["symbol"],
                                    "error": f"need >={_MIN_HISTORY} candles, got {len(df)}"}
                    continue
                prepared.append({"idx": idx, "symbol": item["symbol"], "df": df})
            except Exception as exc:  # noqa: BLE001
                results[idx] = {"symbol": item.get("symbol", "?"), "error": str(exc)}

        if prepared:
            common_len = min(self.cfg.default_lookback, min(len(p["df"]) for p in prepared))
            common_len = max(common_len, _MIN_HISTORY)
            t0 = time.time()
            self._run_batch(prepared, common_len, pred_len, n_paths, results)
            logger.info("Batch forecast: %d symbols x %d paths in %.1fs on %s",
                        len(prepared), n_paths, time.time() - t0, self.device)

        return [results[i] for i in range(len(items))]

    # ── batched inference ─────────────────────────────────────────────────
    def _run_batch(self, prepared, common_len, pred_len, n_paths, results) -> None:
        # Build the expanded Monte-Carlo batch (each symbol repeated n_paths).
        df_list, x_ts_list, y_ts_list, owner = [], [], [], []
        for p in prepared:
            df = p["df"].iloc[-common_len:].reset_index(drop=True)
            x_ts = df["ts"]
            y_ts = self._future_timestamps(x_ts, pred_len)
            x_df = df[_PRICE_COLS + ["volume"]].reset_index(drop=True)
            for _ in range(n_paths):
                df_list.append(x_df)
                x_ts_list.append(x_ts.reset_index(drop=True))
                y_ts_list.append(y_ts)
                owner.append(p["idx"])

        # Run in chunks; collect prediction frames in order.
        preds: list = []
        for start in range(0, len(df_list), _MAX_SERIES_PER_CALL):
            sl = slice(start, start + _MAX_SERIES_PER_CALL)
            chunk = self.predictor.predict_batch(
                df_list=df_list[sl], x_timestamp_list=x_ts_list[sl],
                y_timestamp_list=y_ts_list[sl], pred_len=pred_len,
                T=self.cfg.kronos_t, top_p=self.cfg.kronos_top_p,
                sample_count=1, verbose=False)
            preds.extend(chunk)

        # Regroup by symbol and summarise.
        by_idx: dict[int, list] = {}
        for o, pred_df in zip(owner, preds):
            by_idx.setdefault(o, []).append(pred_df)

        for p in prepared:
            paths = by_idx.get(p["idx"], [])
            current_close = float(p["df"]["close"].iloc[-1])
            y_ts = self._future_timestamps(p["df"]["ts"].iloc[-common_len:], pred_len)
            results[p["idx"]] = self._summarise(p["symbol"], current_close, paths, y_ts)

    # ── summary statistics ────────────────────────────────────────────────
    @staticmethod
    def _summarise(symbol, current_close, paths, y_timestamp) -> dict:
        if not paths:
            return {"symbol": symbol, "error": "no forecast produced"}

        closes = np.array([p["close"].to_numpy(dtype=float) for p in paths])   # (K, P)
        highs = np.array([p["high"].to_numpy(dtype=float) for p in paths])
        lows = np.array([p["low"].to_numpy(dtype=float) for p in paths])
        opens = np.array([p["open"].to_numpy(dtype=float) for p in paths])
        vols = np.array([p["volume"].to_numpy(dtype=float) for p in paths])

        denom = current_close or 1.0
        terminal_ret = closes[:, -1] / denom - 1.0
        P = closes.shape[1]

        # Multi-horizon probabilities from the SAME path cloud (free). A single
        # long-horizon prob pins to 0/100 for trending names; reporting 1m/3m and
        # a blend communicates the real uncertainty and tempers overconfidence.
        def _horizon(step):
            idx = min(step, P) - 1
            rr = closes[:, idx] / denom - 1.0
            return float((rr > 0).mean()), float(rr.mean()) * 100.0
        p1, e1 = _horizon(21)    # ~1 month
        p3, e3 = _horizon(63)    # ~3 months
        p_term = float((terminal_ret > 0).mean())
        prob_blend = (p1 + p3 + p_term) / 3.0

        mean_close = closes.mean(axis=0)
        mean_high = highs.mean(axis=0)
        mean_low = lows.mean(axis=0)

        # Per-step 95% confidence cone (2.5/97.5 pct) for the UI fan chart.
        # NOTE: field names stay q05/q95 = lower/upper bound (now a 95% CI).
        q05 = np.percentile(closes, 2.5, axis=0)
        q50 = np.percentile(closes, 50, axis=0)
        q95 = np.percentile(closes, 97.5, axis=0)

        # Forward per-step volatility (median across paths of intra-path log-ret std).
        with np.errstate(divide="ignore", invalid="ignore"):
            log_ret = np.diff(np.log(np.clip(closes, 1e-9, None)), axis=1)
        step_vol = float(np.nan_to_num(np.median(np.std(log_ret, axis=1))))

        ts_list = [t.isoformat() for t in pd.to_datetime(y_timestamp)]
        candles = [{
            "ts": ts_list[i] if i < len(ts_list) else None,
            "open": round(float(opens.mean(axis=0)[i]), 6),
            "high": round(float(mean_high[i]), 6),
            "low": round(float(mean_low[i]), 6),
            "close": round(float(mean_close[i]), 6),
            "volume": round(float(vols.mean(axis=0)[i]), 4),
        } for i in range(closes.shape[1])]

        forecast_high = float(mean_high.max())
        forecast_low = float(mean_low.min())

        # ── rich Kronos features (path-intrinsic; no levels needed) ──
        ph_max = highs.max(axis=1)            # per-path best high
        pl_min = lows.min(axis=1)             # per-path worst low
        mfe = float((ph_max / denom - 1).mean()) * 100      # max favorable excursion
        mae = float((pl_min / denom - 1).mean()) * 100      # max adverse excursion
        exp_range = float(((ph_max - pl_min) / denom).mean()) * 100
        sd_t = float(terminal_ret.std()) or 1e-9
        skew = float((((terminal_ret - terminal_ret.mean()) / sd_t) ** 3).mean())
        worst = np.sort(terminal_ret)[:max(1, int(len(terminal_ret) * 0.05))]
        cvar5 = float(worst.mean()) * 100
        third = max(1, vols.shape[1] // 3)
        v_first = float(vols[:, :third].mean()); v_last = float(vols[:, -third:].mean())
        vol_trend = float((v_last - v_first) / (v_first + 1e-9))
        features = {
            "expected_range_pct": round(exp_range, 3),
            "mae_pct": round(mae, 3),                 # expected worst dip (long)
            "mfe_pct": round(mfe, 3),                 # expected best pop
            "skew": round(skew, 3),                   # >0 = fat upside
            "cvar5_pct": round(cvar5, 3),             # mean of worst 5% outcomes
            "prob_up_5pct": round(float((terminal_ret > 0.05).mean()), 3),
            "prob_dn_5pct": round(float((terminal_ret < -0.05).mean()), 3),
            "vol_trend": round(vol_trend, 3),         # predicted volume slope
            "ret_vol_ratio": round(float(terminal_ret.mean()) / sd_t, 3),  # Sharpe-like
        }

        return {
            "symbol": symbol,
            "n_paths": int(closes.shape[0]),
            "current_close": round(current_close, 6),
            "forecast_candles": candles,
            "forecast_close": round(float(mean_close[-1]), 6),
            "forecast_high": round(forecast_high, 6),
            "forecast_low": round(forecast_low, 6),
            "expected_return_pct": round(float(terminal_ret.mean()) * 100, 4),
            "path_spread_pct": round((forecast_high - forecast_low) / denom * 100, 4),
            # ── probabilistic fields ──
            # Headline prob_up is the multi-horizon blend (less overconfident than
            # a single 90-day terminal). prob_up_terminal keeps the raw value.
            "prob_up": round(prob_blend, 4),
            "prob_up_terminal": round(p_term, 4),
            "prob_up_1m": round(p1, 4),
            "prob_up_3m": round(p3, 4),
            "exp_ret_1m_pct": round(e1, 4),
            "exp_ret_3m_pct": round(e3, 4),
            "ret_q05_pct": round(float(np.percentile(terminal_ret, 2.5)) * 100, 4),
            "ret_q50_pct": round(float(np.percentile(terminal_ret, 50)) * 100, 4),
            "ret_q95_pct": round(float(np.percentile(terminal_ret, 97.5)) * 100, 4),
            "terminal_vol_pct": round(float(terminal_ret.std()) * 100, 4),
            "step_vol_pct": round(step_vol * 100, 4),
            "cone": {
                "q05": [round(float(x), 6) for x in q05],
                "q50": [round(float(x), 6) for x in q50],
                "q95": [round(float(x), 6) for x in q95],
            },
            "features": features,
        }

    # ── frame helpers ─────────────────────────────────────────────────────
    @staticmethod
    def _to_frame(ohlcv: list[dict]) -> pd.DataFrame:
        df = pd.DataFrame(ohlcv)
        if "ts" not in df.columns:
            for alt in ("timestamp", "timestamps", "date", "time"):
                if alt in df.columns:
                    df = df.rename(columns={alt: "ts"})
                    break
        missing = [c for c in _PRICE_COLS if c not in df.columns]
        if missing:
            raise ValueError(f"OHLCV missing columns: {missing}")
        if "volume" not in df.columns:
            df["volume"] = 0.0
        if "ts" not in df.columns:
            df["ts"] = pd.date_range(end=pd.Timestamp.utcnow().normalize(),
                                     periods=len(df), freq="D")
        df["ts"] = pd.to_datetime(df["ts"], errors="coerce", utc=False)
        df = df.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)
        for col in _PRICE_COLS + ["volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=_PRICE_COLS).reset_index(drop=True)
        df["volume"] = df["volume"].fillna(0.0)
        return df

    @staticmethod
    def _future_timestamps(x_timestamp: pd.Series, pred_len: int) -> pd.Series:
        ts = pd.to_datetime(x_timestamp).reset_index(drop=True)
        step = ts.diff().dropna().median() if len(ts) >= 2 else pd.Timedelta(days=1)
        if not isinstance(step, pd.Timedelta) or step <= pd.Timedelta(0):
            step = pd.Timedelta(days=1)
        last = ts.iloc[-1]
        return pd.Series(pd.to_datetime([last + step * (i + 1) for i in range(pred_len)]))
