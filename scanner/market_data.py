"""Free OHLCV fallback via Yahoo Finance's chart API (no API key).

Used when OpenAlice has no price history for a symbol — which lets index and
crypto scans run with no OpenAlice at all (handy for CI / 24-7 signal jobs).

Endpoint (no auth):
    https://query1.finance.yahoo.com/v8/finance/chart/<symbol>?range=2y&interval=1d
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("scanner.market_data")

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Vigil/1.0"
_HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]


def to_yahoo_symbol(symbol: str) -> str:
    s = symbol.strip()
    up = s.upper()
    if up.startswith("^") or "." in s or "-" in s:
        return s                       # index / exchange-qualified / already crypto
    if up.endswith("USDT"):
        return up[:-4] + "-USD"
    if up.endswith("USD"):
        return up[:-3] + "-USD"        # BTCUSD -> BTC-USD
    return up                          # plain equity, e.g. AAPL


async def fallback_ohlcv(symbol: str, bars: int = 450) -> list[dict]:
    sym = to_yahoo_symbol(symbol)
    rng = "5y" if bars > 380 else ("2y" if bars > 130 else "1y")
    params = {"range": rng, "interval": "1d"}
    for host in _HOSTS:
        url = f"https://{host}/v8/finance/chart/{sym}"
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True,
                                         headers={"User-Agent": _UA}) as client:
                r = await client.get(url, params=params)
            if r.status_code != 200:
                continue
            out = _parse(r.json(), bars)
            if out:
                logger.info("Yahoo fallback: %s -> %d candles", symbol, len(out))
                return out
        except Exception as exc:  # noqa: BLE001
            logger.debug("Yahoo fallback %s via %s failed: %s", symbol, host, exc)
            continue
    logger.warning("Yahoo fallback: no data for %s (%s)", symbol, sym)
    return []


def _parse(payload: dict, bars: int) -> list[dict]:
    try:
        result = payload["chart"]["result"][0]
        ts = result["timestamp"]
        q = result["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError):
        return []
    import datetime as _dt
    o, h, l, c = q.get("open"), q.get("high"), q.get("low"), q.get("close")
    v = q.get("volume") or [0] * len(ts)
    rows = []
    for i in range(len(ts)):
        if None in (o[i], h[i], l[i], c[i]):
            continue
        rows.append({
            "ts": _dt.datetime.utcfromtimestamp(ts[i]).strftime("%Y-%m-%d"),
            "open": float(o[i]), "high": float(h[i]), "low": float(l[i]),
            "close": float(c[i]), "volume": float(v[i] or 0),
        })
    return rows[-bars:]
