"""Data-quality guardrails — quarantine garbage before it becomes a pick.

Forecasting on bad data produces confident nonsense. Before a name reaches
Kronos we check its OHLCV for the usual pathologies: too little history, penny
prices, illiquidity (lots of zero-volume bars), split/spike artifacts (giant
single-day jumps), and dead/flat series. Critical issues quarantine the name
(dropped from the scan); softer issues become a `data_warning` flag shown on the
pick so you know to look twice.
"""

from __future__ import annotations


def analyze(symbol: str, ohlcv: list[dict], min_bars: int = 120) -> dict:
    flags: list[str] = []
    if not ohlcv or len(ohlcv) < min_bars:
        return {"ok": False, "quarantine": True, "flags": ["insufficient_history"]}

    closes = [r.get("close") for r in ohlcv if r.get("close") is not None]
    vols = [r.get("volume") or 0 for r in ohlcv]
    if len(closes) < min_bars:
        return {"ok": False, "quarantine": True, "flags": ["insufficient_history"]}

    quarantine = False
    last = closes[-1]

    if isinstance(last, (int, float)) and last < 1.0:
        flags.append("penny_stock")

    zero_vol = sum(1 for v in vols if not v) / len(vols)
    if zero_vol > 0.2:
        flags.append(f"illiquid_{int(zero_vol*100)}pct_zero_vol")
        if zero_vol > 0.5:
            quarantine = True

    jumps = sum(1 for a, b in zip(closes, closes[1:])
                if a and b and abs(b / a - 1) > 0.5)
    if jumps:
        flags.append(f"price_jumps_{jumps}")          # possible split/bad print
        if jumps >= 3:
            quarantine = True

    recent = closes[-30:]
    if len(set(round(c, 6) for c in recent)) <= 2:
        flags.append("stale_or_flat")
        quarantine = True

    return {"ok": not quarantine, "quarantine": quarantine, "flags": flags}
