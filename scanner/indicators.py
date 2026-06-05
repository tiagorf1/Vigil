"""Local technical indicators computed in pandas from a single OHLCV frame.

This replaces per-symbol round-trips to OpenAlice's calculateIndicator tool:
we already fetch OHLCV for Kronos, so computing RSI/MACD/SMA/ATR/BBands here is
~6x fewer network calls per symbol, deterministic, and unit-testable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_PRICE_COLS = ["open", "high", "low", "close"]


def ohlcv_to_frame(ohlcv: list[dict]) -> pd.DataFrame:
    """Coerce a list of candle dicts into a clean, time-sorted DataFrame."""
    df = pd.DataFrame(ohlcv or [])
    if df.empty:
        return df
    if "ts" not in df.columns:
        for alt in ("timestamp", "timestamps", "date", "time"):
            if alt in df.columns:
                df = df.rename(columns={alt: "ts"})
                break
    for col in _PRICE_COLS + ["volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], errors="coerce", utc=False)
        df = df.sort_values("ts")
    df = df.dropna(subset=[c for c in _PRICE_COLS if c in df.columns]).reset_index(drop=True)
    return df


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    # Wilder's smoothing
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(100.0)  # zero losses => max strength


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def sma(close: pd.Series, period: int) -> pd.Series:
    return close.rolling(window=period, min_periods=max(2, period // 2)).mean()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def bbands(close: pd.Series, period: int = 20, num_std: float = 2.0):
    mid = close.rolling(window=period, min_periods=max(2, period // 2)).mean()
    std = close.rolling(window=period, min_periods=max(2, period // 2)).std(ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


def compute_all(ohlcv: list[dict]) -> dict:
    """Return the latest value of every indicator the screener/report needs.

    Missing/short data yields None for the affected fields, never an exception.
    """
    df = ohlcv_to_frame(ohlcv)
    out = {
        "price": None, "rsi14": None, "macd_hist": None, "macd_hist_prev": None,
        "sma50": None, "sma200": None, "atr14": None,
        "bb_upper": None, "bb_mid": None, "bb_lower": None,
        "ret_7d": None, "ret_30d": None, "vol_vs_avg": None,
    }
    if df.empty or "close" not in df:
        return out

    close = df["close"]
    out["price"] = _last(close)

    if len(close) >= 15:
        out["rsi14"] = _last(rsi(close))
    if len(close) >= 26:
        _, _, hist = macd(close)
        out["macd_hist"] = _last(hist)
        out["macd_hist_prev"] = _last(hist, offset=1)
    if len(close) >= 25:
        out["sma50"] = _last(sma(close, 50))
    if len(close) >= 100:
        out["sma200"] = _last(sma(close, 200))
    if len(df) >= 15 and {"high", "low"}.issubset(df.columns):
        out["atr14"] = _last(atr(df))
    if len(close) >= 10:
        u, m, l = bbands(close)
        out["bb_upper"], out["bb_mid"], out["bb_lower"] = _last(u), _last(m), _last(l)

    # crypto momentum helpers
    if len(close) >= 8 and close.iloc[-8] > 0:
        out["ret_7d"] = float(close.iloc[-1] / close.iloc[-8] - 1)
    if len(close) >= 31 and close.iloc[-31] > 0:
        out["ret_30d"] = float(close.iloc[-1] / close.iloc[-31] - 1)
    if "volume" in df and len(df) >= 31:
        avg30 = df["volume"].iloc[-31:-1].mean()
        if avg30 and not np.isnan(avg30):
            out["vol_vs_avg"] = float(df["volume"].iloc[-1] / avg30)

    out.update(_performance_metrics(df, close))
    return out


def _performance_metrics(df: pd.DataFrame, close: pd.Series) -> dict:
    """Trailing-return, volatility, range and drawdown metrics for the report."""
    px = float(close.iloc[-1])
    m: dict = {
        "ret_1m": None, "ret_3m": None, "ret_6m": None, "ret_1y": None,
        "ann_vol_pct": None, "hi_52w": None, "lo_52w": None,
        "pct_from_52w_hi": None, "pct_from_52w_lo": None,
        "max_drawdown_1y_pct": None, "dist_sma50_pct": None,
        "dist_sma200_pct": None, "avg_vol_30d": None,
    }

    def trailing(n):
        if len(close) > n and close.iloc[-n - 1] > 0:
            return float(close.iloc[-1] / close.iloc[-n - 1] - 1) * 100
        return None

    m["ret_1m"], m["ret_3m"] = trailing(21), trailing(63)
    m["ret_6m"], m["ret_1y"] = trailing(126), trailing(252)

    rets = close.pct_change().dropna()
    if len(rets) >= 20:
        m["ann_vol_pct"] = float(rets.tail(252).std() * (252 ** 0.5) * 100)

    window = close.tail(252)
    if len(window) >= 30:
        hi, lo = float(window.max()), float(window.min())
        m["hi_52w"], m["lo_52w"] = round(hi, 4), round(lo, 4)
        if hi:
            m["pct_from_52w_hi"] = round((px / hi - 1) * 100, 2)
        if lo:
            m["pct_from_52w_lo"] = round((px / lo - 1) * 100, 2)
        running_max = window.cummax()
        dd = (window / running_max - 1.0)
        m["max_drawdown_1y_pct"] = round(float(dd.min()) * 100, 2)

    sma50 = close.rolling(50, min_periods=25).mean().iloc[-1]
    sma200 = close.rolling(200, min_periods=100).mean().iloc[-1]
    if sma50 and not np.isnan(sma50):
        m["dist_sma50_pct"] = round((px / float(sma50) - 1) * 100, 2)
    if sma200 and not np.isnan(sma200):
        m["dist_sma200_pct"] = round((px / float(sma200) - 1) * 100, 2)
    if "volume" in df and len(df) >= 30:
        av = df["volume"].tail(30).mean()
        if av and not np.isnan(av):
            m["avg_vol_30d"] = round(float(av), 2)

    # round the trailing returns
    for k in ("ret_1m", "ret_3m", "ret_6m", "ret_1y", "ann_vol_pct"):
        if isinstance(m[k], (int, float)):
            m[k] = round(m[k], 2)
    return m


def _last(series: pd.Series, offset: int = 0):
    if series is None or len(series) <= offset:
        return None
    val = series.iloc[-(1 + offset)]
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    return float(val)
