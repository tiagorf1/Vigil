"""Factor library — documented, decades-robust cross-sectional signals.

Each factor takes a symbol's OHLCV history (list of {ts,open,high,low,close,
volume}) and returns a single float score where HIGHER = more bullish, so the
universe can be ranked. These are public, researched edges — not a proprietary
oracle. Whether each actually works in our universe is decided by
`factor_backtest` (Information Coefficient), never assumed.

Factors implemented:
  momentum_12_1   cross-sectional momentum (12m return skipping the last month)
  trend_ts        time-series trend (price vs 200d SMA)
  reversal_5d     short-term reversal (fade the last week) — contrarian
  low_vol         low-volatility anomaly (inverse trailing vol)
  volume_mom      volume-confirmed momentum (OBV slope) — your volume idea
"""

from __future__ import annotations

import numpy as np


def _closes(ohlcv: list[dict]) -> np.ndarray:
    return np.array([r.get("close") for r in ohlcv if r.get("close") is not None], dtype=float)


def _volumes(ohlcv: list[dict]) -> np.ndarray:
    return np.array([r.get("volume") or 0.0 for r in ohlcv], dtype=float)


def momentum_12_1(ohlcv: list[dict]) -> float | None:
    """12-month return, skipping the most recent ~21 days (classic momentum:
    the last month is excluded because it carries short-term reversal)."""
    c = _closes(ohlcv)
    if len(c) < 252:
        return None
    return float(c[-21] / c[-252] - 1.0)


def trend_ts(ohlcv: list[dict]) -> float | None:
    """Time-series trend: percentage distance of price above its 200d average."""
    c = _closes(ohlcv)
    if len(c) < 200:
        return None
    sma200 = float(np.mean(c[-200:]))
    return float(c[-1] / sma200 - 1.0) if sma200 else None


def reversal_5d(ohlcv: list[dict]) -> float | None:
    """Short-term reversal: the NEGATIVE of the last-5-day return (buy the
    oversold, fade the overbought). Contrarian — strongest in choppy regimes."""
    c = _closes(ohlcv)
    if len(c) < 6:
        return None
    return float(-(c[-1] / c[-6] - 1.0))


def low_vol(ohlcv: list[dict], win: int = 60) -> float | None:
    """Low-volatility anomaly: inverse of trailing realised vol (low-vol names
    earn better risk-adjusted returns). Score = -vol, so calmer = higher."""
    c = _closes(ohlcv)
    if len(c) < win + 1:
        return None
    rets = np.diff(c[-(win + 1):]) / c[-(win + 1):-1]
    v = float(np.std(rets))
    return -v


def volume_mom(ohlcv: list[dict], win: int = 20) -> float | None:
    """Volume-confirmed momentum via On-Balance-Volume slope: accumulate signed
    volume (up days +, down days -) and measure its recent trend, normalised by
    average volume. Rising OBV = buying pressure confirming the move."""
    c = _closes(ohlcv)
    vol = _volumes(ohlcv)
    if len(c) < win + 1 or len(vol) < len(c):
        return None
    vol = vol[-len(c):]
    sign = np.sign(np.diff(c))
    obv = np.concatenate([[0.0], np.cumsum(sign * vol[1:])])
    seg = obv[-win:]
    avg_vol = float(np.mean(vol[-win:])) or 1.0
    # slope of OBV over the window, per bar, scaled by typical volume
    x = np.arange(len(seg), dtype=float)
    slope = float(np.polyfit(x, seg, 1)[0]) if len(seg) >= 2 else 0.0
    return slope / avg_vol


# name -> (callable, description); the backtester evaluates each independently.
FACTORS = {
    "momentum_12_1": (momentum_12_1, "12m return skipping last month"),
    "trend_ts": (trend_ts, "price vs 200d SMA"),
    "reversal_5d": (reversal_5d, "fade last 5d (contrarian)"),
    "low_vol": (low_vol, "inverse trailing vol"),
    "volume_mom": (volume_mom, "OBV slope (volume-confirmed)"),
}


def score_all(ohlcv: list[dict]) -> dict[str, float | None]:
    """Compute every factor for one symbol's history."""
    return {name: fn(ohlcv) for name, (fn, _) in FACTORS.items()}
