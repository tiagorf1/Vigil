"""Company / instrument name resolution + symbol sanity-check.

Two jobs:
  * give every symbol a human name (so the UI doesn't show bare tickers);
  * validate that a symbol is a real tradeable instrument (equity / index /
    crypto / ETF), so universe searches can't drag in odd product categories.

Uses Yahoo Finance's free search endpoint (no key), cached on disk.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger("scanner.names")

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Vigil/1.0"
_VALID_TYPES = {"EQUITY", "INDEX", "ETF", "CRYPTOCURRENCY", "CURRENCY", "MUTUALFUND"}

INDEX_NAMES = {
    "^GSPC": "S&P 500", "^DJI": "Dow Jones Industrial", "^IXIC": "Nasdaq Composite",
    "^RUT": "Russell 2000", "^VIX": "CBOE Volatility Index", "^FTSE": "FTSE 100",
    "^GDAXI": "DAX", "^FCHI": "CAC 40", "^AEX": "AEX", "^STOXX50E": "Euro Stoxx 50",
    "^N225": "Nikkei 225", "^HSI": "Hang Seng", "000001.SS": "Shanghai Composite",
    "^BSESN": "BSE Sensex", "^AXJO": "ASX 200", "^GSPTSE": "S&P/TSX Composite",
}
CRYPTO_NAMES = {
    "BTCUSD": "Bitcoin", "ETHUSD": "Ethereum", "SOLUSD": "Solana", "BNBUSD": "BNB",
    "XRPUSD": "XRP", "ADAUSD": "Cardano", "AVAXUSD": "Avalanche", "DOTUSD": "Polkadot",
}
MARKET_NAMES = {
    "GC=F": "Gold Futures", "SI=F": "Silver Futures", "CL=F": "WTI Crude Oil Futures",
    "BZ=F": "Brent Crude Oil Futures", "NG=F": "Natural Gas Futures",
    "HG=F": "Copper Futures", "PL=F": "Platinum Futures", "PA=F": "Palladium Futures",
    "ZC=F": "Corn Futures", "ZW=F": "Wheat Futures", "ZS=F": "Soybean Futures",
    "KC=F": "Coffee Futures", "SB=F": "Sugar Futures", "CT=F": "Cotton Futures",
    "EURUSD=X": "EUR/USD", "GBPUSD=X": "GBP/USD", "USDJPY=X": "USD/JPY",
    "USDCHF=X": "USD/CHF", "USDCAD=X": "USD/CAD", "AUDUSD=X": "AUD/USD",
    "NZDUSD=X": "NZD/USD", "EURJPY=X": "EUR/JPY", "GBPJPY=X": "GBP/JPY",
    "EURGBP=X": "EUR/GBP",
}


def _static_name(symbol: str) -> str | None:
    up = symbol.upper()
    return INDEX_NAMES.get(up) or CRYPTO_NAMES.get(up) or MARKET_NAMES.get(up)


def _cache():
    try:
        from scanner.cache import DiskCache
        return DiskCache("names", ttl_seconds=30 * 86_400)
    except Exception:  # noqa: BLE001
        return None


async def resolve(symbol: str) -> dict:
    """Return {name, quote_type, valid} for a symbol."""
    static = _static_name(symbol)
    if static:
        if symbol.upper() in INDEX_NAMES:
            qt = "INDEX"
        elif symbol.upper() in CRYPTO_NAMES:
            qt = "CRYPTOCURRENCY"
        else:
            qt = "FUTURE" if symbol.upper().endswith("=F") else "CURRENCY"
        return {"name": static, "quote_type": qt, "valid": True}

    cache = _cache()
    if cache is not None:
        hit = cache.get(f"name:{symbol}")
        if hit is not None:
            return hit

    info = await _yahoo_search(symbol)
    if cache is not None and info.get("name"):
        cache.set(f"name:{symbol}", info)
    return info


async def _yahoo_search(symbol: str) -> dict:
    url = "https://query2.finance.yahoo.com/v1/finance/search"
    params = {"q": symbol, "quotesCount": 4, "newsCount": 0}
    try:
        async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": _UA}) as client:
            r = await client.get(url, params=params)
        if r.status_code != 200:
            return {"name": symbol, "quote_type": None, "valid": True}
        quotes = r.json().get("quotes", [])
        up = symbol.upper()
        # Prefer an exact symbol match.
        match = next((q for q in quotes if str(q.get("symbol", "")).upper() == up), None)
        match = match or (quotes[0] if quotes else None)
        if not match:
            return {"name": symbol, "quote_type": None, "valid": False}
        name = match.get("longname") or match.get("shortname") or symbol
        qt = (match.get("quoteType") or "").upper()
        return {"name": name, "quote_type": qt, "valid": qt in _VALID_TYPES}
    except Exception as exc:  # noqa: BLE001
        logger.debug("name resolve failed for %s: %s", symbol, exc)
        return {"name": symbol, "quote_type": None, "valid": True}


async def resolve_many(symbols: list[str], concurrency: int = 8) -> dict[str, dict]:
    sem = asyncio.Semaphore(concurrency)

    async def one(s):
        async with sem:
            return s, await resolve(s)

    pairs = await asyncio.gather(*[one(s) for s in symbols])
    return dict(pairs)
