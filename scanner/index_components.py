"""Index / ETF component universe expansion.

The scanner should not forecast SPY or ^GSPC as the "idea". For index-style
scans, it expands liquid ETF/index aliases into their component companies, then
the ordinary equity screener does the work.

Component lists are small JSON cache entries. They are refreshed weekly because
index membership changes, but not so often that startup fills disk or hammers
public pages.
"""

from __future__ import annotations

import io
import csv
import logging

import httpx
import pandas as pd

logger = logging.getLogger("scanner.index_components")

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Vigil/1.0"

# Brokerage-friendly, liquid ETF handles for user-facing presets.
INDEX_ETF_PRESETS = {
    "us": ["SPY", "QQQ", "DIA"],
    "world": ["SPY", "QQQ", "DIA"],
    "sp500": ["SPY"],
    "s&p": ["SPY"],
    "s&p 500": ["SPY"],
    "nasdaq": ["QQQ"],
    "nasdaq100": ["QQQ"],
    "nasdaq 100": ["QQQ"],
    "dow": ["DIA"],
    "dow 30": ["DIA"],
}

ETF_LABELS = {
    "SPY": "SPDR S&P 500 ETF Trust",
    "QQQ": "Invesco QQQ Trust",
    "DIA": "SPDR Dow Jones Industrial Average ETF Trust",
    "IWM": "iShares Russell 2000 ETF",
}

SECTOR_ETFS = [
    "XLK",  # Technology
    "XLF",  # Financials
    "XLV",  # Health Care
    "XLE",  # Energy
    "XLY",  # Consumer Discretionary
    "XLP",  # Consumer Staples
    "XLI",  # Industrials
    "XLB",  # Materials
    "XLU",  # Utilities
    "XLRE", # Real Estate
    "XLC",  # Communication Services
]

ETF_TO_COMPONENT_SOURCE = {
    "SPY": "sp500",
    "QQQ": "nasdaq100",
    "DIA": "dow30",
}

_DOW30_FALLBACK = [
    "AAPL", "AMGN", "AMZN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS",
    "GS", "HD", "HON", "IBM", "JNJ", "JPM", "KO", "MCD", "MMM", "MRK",
    "MSFT", "NKE", "NVDA", "PG", "SHW", "TRV", "UNH", "V", "VZ", "WMT",
]


async def expand_index_directive(directive: str) -> tuple[list[str], list[str]]:
    """Return (component_symbols, etf_symbols_used)."""
    etfs = preset_etfs(directive)
    if not etfs:
        etfs = ["SPY", "QQQ", "DIA"]

    symbols: list[str] = []
    for etf in etfs:
        symbols.extend(await components_for_etf(etf))
    return _dedupe(symbols), etfs


def preset_etfs(directive: str) -> list[str]:
    key = (directive or "world").lower().strip()
    key = key.replace("-", " ")
    if key in INDEX_ETF_PRESETS:
        return list(INDEX_ETF_PRESETS[key])
    for k, etfs in INDEX_ETF_PRESETS.items():
        if k in key:
            return list(etfs)
    up = key.upper()
    if up in ETF_LABELS:
        return [up]
    return []


def sector_etfs_for_directive(directive: str) -> list[str]:
    """Sector sleeves to forecast as context for broad/index scans."""
    key = (directive or "").lower()
    if any(k in key for k in ("s&p", "sp500", "sp 500", "us", "world", "index")):
        return list(SECTOR_ETFS)
    return []


async def components_for_etf(etf: str) -> list[str]:
    etf = etf.upper()
    source = ETF_TO_COMPONENT_SOURCE.get(etf)
    if source is None:
        logger.warning("%s component expansion is not implemented yet", etf)
        return []

    cache = _cache()
    key = f"components:{source}"
    if cache is not None:
        hit = cache.get(key)
        if hit:
            return list(hit)

    if source == "sp500":
        symbols = await _csv_symbols(
            "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv",
            symbol_columns=("Symbol",),
        )
        if not symbols:
            symbols = await _wikipedia_symbols(
                "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                symbol_columns=("Symbol",),
            )
    elif source == "nasdaq100":
        symbols = await _json_symbols(
            "https://historyofmarket.com/api/nasdaq/100.json",
            list_key="companies",
            symbol_keys=("ticker", "symbol"),
        )
        if not symbols:
            symbols = await _csv_symbols(
                "https://topforeignstocks.com/wp-content/uploads/2026/02/Complete-List-of-NASDAQ-100-Constituents-Feb-1-2026.csv",
                symbol_columns=("Ticker", "Symbol"),
            )
        if not symbols:
            symbols = await _wikipedia_symbols(
                "https://en.wikipedia.org/wiki/Nasdaq-100",
                symbol_columns=("Ticker",),
            )
    elif source == "dow30":
        symbols = list(_DOW30_FALLBACK)
    else:
        symbols = []

    symbols = [_normalise_symbol(s) for s in symbols]
    symbols = [s for s in symbols if s]
    symbols = _dedupe(symbols)
    if cache is not None and symbols:
        cache.set(key, symbols)
    logger.info("%s -> %d components", etf, len(symbols))
    return symbols


async def _wikipedia_symbols(url: str, symbol_columns: tuple[str, ...]) -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": _UA}) as client:
            r = await client.get(url)
        r.raise_for_status()
        tables = pd.read_html(io.StringIO(r.text))
    except Exception as exc:  # noqa: BLE001
        logger.warning("component fetch failed for %s: %s", url, exc)
        return []

    for table in tables:
        columns = [str(c).strip() for c in table.columns]
        for wanted in symbol_columns:
            if wanted in columns:
                values = table[wanted].dropna().astype(str).tolist()
                if len(values) >= 20:
                    return values
    return []


async def _csv_symbols(url: str, symbol_columns: tuple[str, ...]) -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": _UA}) as client:
            r = await client.get(url)
        r.raise_for_status()
        rows = list(csv.DictReader(io.StringIO(r.text)))
    except Exception as exc:  # noqa: BLE001
        logger.warning("component csv fetch failed for %s: %s", url, exc)
        return []
    for wanted in symbol_columns:
        values = [row.get(wanted, "") for row in rows if row.get(wanted)]
        if len(values) >= 20:
            return values
    return []


async def _json_symbols(url: str, list_key: str, symbol_keys: tuple[str, ...]) -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": _UA}) as client:
            r = await client.get(url)
        r.raise_for_status()
        payload = r.json()
        rows = payload.get(list_key, []) if isinstance(payload, dict) else []
    except Exception as exc:  # noqa: BLE001
        logger.warning("component json fetch failed for %s: %s", url, exc)
        return []
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in symbol_keys:
            value = row.get(key)
            if value:
                out.append(str(value))
                break
    return out if len(out) >= 20 else []


def _normalise_symbol(symbol: str) -> str:
    s = str(symbol).strip().upper()
    if not s or s in {"NAN", "NONE"}:
        return ""
    # Wikipedia uses BRK.B / BF.B; Yahoo and most broker APIs accept BRK-B / BF-B.
    return s.replace(".", "-")


def _cache():
    try:
        from scanner.cache import DiskCache
        return DiskCache("index_components", ttl_seconds=7 * 86_400)
    except Exception:  # noqa: BLE001
        return None


def _dedupe(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out
