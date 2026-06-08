"""Technical entry/exit engine — structure-based levels + confluence.

Replaces the crude "ATR box" entry/stop/target with proper, codeable technical
analysis: trend filter, trend-strength (ADX), swing-structure support/resistance,
entry triggers (pullback / breakout / oversold turn), and an adaptive
(ATR-trailing) exit. Returns concrete levels, an R:R, and a confluence score so
a setup only counts when several independent signals agree.

All standard, public technical concepts — implemented from scratch here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from scanner import indicators as ind


def _adx(df: pd.DataFrame, period: int = 14) -> float | None:
    if len(df) < period * 2:
        return None
    h, l, c = df["high"], df["low"], df["close"]
    up = h.diff()
    dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    pdi = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, np.nan)
    mdi = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()
    v = adx.iloc[-1]
    return float(v) if pd.notna(v) else None


def _swings(close: pd.Series, win: int = 5):
    """Return (supports below price, resistances above price) from local pivots."""
    n = len(close)
    sup, res = [], []
    px = float(close.iloc[-1])
    arr = close.to_numpy()
    for i in range(win, n - win):
        seg = arr[i - win:i + win + 1]
        if arr[i] == seg.min():
            sup.append(float(arr[i]))
        if arr[i] == seg.max():
            res.append(float(arr[i]))
    supports = sorted([s for s in sup if s < px], reverse=True)
    resistances = sorted([r for r in res if r > px])
    return supports, resistances


def analyze(ohlcv: list[dict], direction: str = "long") -> dict:
    """Structure-based entry/stop/target + confluence for a long setup."""
    out = {"setup": None, "entry_zone": None, "stop": None, "target": None,
           "rr": None, "confluence": 0, "signals": [], "adx": None, "trend": None}
    df = ind.ohlcv_to_frame(ohlcv)
    if df.empty or len(df) < 60:
        return out

    close = df["close"]
    px = float(close.iloc[-1])
    atr = float(ind.atr(df).iloc[-1] or px * 0.02)
    sma50 = float(ind.sma(close, 50).iloc[-1]) if len(close) >= 50 else None
    sma200 = float(ind.sma(close, 200).iloc[-1]) if len(close) >= 200 else None
    ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
    rsi = float(ind.rsi(close).iloc[-1])
    _, _, hist = ind.macd(close)
    macd_hist = float(hist.iloc[-1])
    adx = _adx(df)
    supports, resistances = _swings(close)
    recent_high = float(close.tail(20).max())

    out["adx"] = round(adx, 1) if adx is not None else None

    # ── confluence signals (long) ──
    sig = []
    uptrend = sma50 is not None and px > sma50 and (sma200 is None or sma50 > sma200)
    if uptrend:
        sig.append("uptrend (price>SMA50>SMA200)")
    out["trend"] = "up" if uptrend else ("down" if sma50 and px < sma50 else "range")
    if adx is not None and adx >= 20:
        sig.append(f"trending (ADX {adx:.0f})")
    if 40 <= rsi <= 65:
        sig.append(f"RSI room ({rsi:.0f})")
    elif rsi < 35:
        sig.append(f"oversold turn ({rsi:.0f})")
    if macd_hist > 0:
        sig.append("MACD positive")
    near_support = supports and (px - supports[0]) / px < 0.04
    if near_support:
        sig.append("pullback to support")
    breakout = px >= recent_high * 0.999
    if breakout:
        sig.append("breakout of 20d high")
    if px > ema20:
        sig.append("above 20-EMA")

    # ── levels ──
    # Stop: just below nearest support, else ATR-based; floor at 1*ATR.
    if supports:
        stop = min(supports[0] * 0.995, px - 1.0 * atr)
    else:
        stop = px - 1.5 * atr
    # Target: nearest resistance above, else 2R projection.
    risk = max(px - stop, 1e-9)
    if resistances:
        target = max(resistances[0], px + 1.5 * risk)
    else:
        target = px + 2.0 * risk
    entry_lo, entry_hi = px - 0.3 * atr, px + 0.3 * atr
    rr = (target - px) / risk if risk > 0 else None

    # Setup label
    if breakout and uptrend:
        setup = "breakout"
    elif near_support and uptrend:
        setup = "pullback"
    elif rsi < 35:
        setup = "mean_reversion"
    elif uptrend:
        setup = "trend_continuation"
    else:
        setup = "neutral"

    out.update({
        "setup": setup,
        "entry_zone": f"${entry_lo:,.2f}-${entry_hi:,.2f}",
        "stop": f"${stop:,.2f}",
        "target": f"${target:,.2f}",
        "rr": f"1:{rr:.1f}" if rr and rr > 0 else "n/a",
        "rr_value": round(rr, 2) if rr else None,
        "entry_value": round(px, 4), "stop_value": round(stop, 4),
        "target_value": round(target, 4),
        "confluence": len(sig),
        "signals": sig,
        "trail_stop": f"${px - 3*atr:,.2f} (3·ATR chandelier)",
        "atr": round(atr, 4),
    })
    return out
