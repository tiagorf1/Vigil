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
                T=1.0, top_p=0.9, sample_count=1, verbose=False)
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
        mean_close = closes.mean(axis=0)
        mean_high = highs.mean(axis=0)
        mean_low = lows.mean(axis=0)

        # Per-step quantile cone (for the UI fan chart).
        q05 = np.percentile(closes, 5, axis=0)
        q50 = np.percentile(closes, 50, axis=0)
        q95 = np.percentile(closes, 95, axis=0)

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
            "prob_up": round(float((terminal_ret > 0).mean()), 4),
            "ret_q05_pct": round(float(np.percentile(terminal_ret, 5)) * 100, 4),
            "ret_q50_pct": round(float(np.percentile(terminal_ret, 50)) * 100, 4),
            "ret_q95_pct": round(float(np.percentile(terminal_ret, 95)) * 100, 4),
            "terminal_vol_pct": round(float(terminal_ret.std()) * 100, 4),
            "step_vol_pct": round(step_vol * 100, 4),
            "cone": {
                "q05": [round(float(x), 6) for x in q05],
                "q50": [round(float(x), 6) for x in q50],
                "q95": [round(float(x), 6) for x in q95],
            },
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
