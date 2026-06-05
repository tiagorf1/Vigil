"""Universe builder.

Turns a free-text directive into a candidate symbol list via OpenAlice search,
falling back to a curated seed list for an empty / broad-sweep directive.
"""

from __future__ import annotations

import logging
import re

from scanner.config import get_config
from scanner.index_components import expand_index_directive
from scanner.names import resolve_many
from scanner.openalice_client import OpenAliceClient

logger = logging.getLogger("scanner.universe")

# Curated fallback universe for an empty directive (from the build plan).
SEED_EQUITIES = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "JPM", "GS", "BAC",
    "XOM", "CVX", "JNJ", "UNH", "PFE", "V", "MA", "WMT", "HD", "DIS", "NFLX",
    "AMD", "INTC", "QCOM", "MU", "ASML", "SAP", "NESN", "NOVN", "ROG", "SAN",
    "BNP", "AXA", "TTE", "SHEL", "HSBA", "LLOY", "GSK", "AZN", "BP",
]
SEED_CRYPTO = [
    "BTCUSD", "ETHUSD", "SOLUSD", "BNBUSD", "XRPUSD", "ADAUSD", "AVAXUSD", "DOTUSD",
]
SEED_COMMODITIES = [
    "GC=F", "SI=F", "CL=F", "BZ=F", "NG=F", "HG=F", "PL=F", "PA=F",
    "ZC=F", "ZW=F", "ZS=F", "KC=F", "SB=F", "CT=F",
]
SEED_FOREX = [
    "EURUSD=X", "GBPUSD=X", "USDJPY=X", "USDCHF=X", "USDCAD=X",
    "AUDUSD=X", "NZDUSD=X", "EURJPY=X", "GBPJPY=X", "EURGBP=X",
]

_CRYPTO_HINTS = {"crypto", "bitcoin", "ethereum", "token", "coin", "defi", "altcoin"}
_COMMODITY_HINTS = {"commodity", "commodities", "futures", "gold", "oil", "metals", "energy"}
_FOREX_HINTS = {"forex", "fx", "currency", "currencies", "eurusd", "usdjpy"}
_INDEX_HINTS = {"index", "indexes", "indices"}
_SYMBOL_RE = re.compile(r"^[A-Z0-9^][A-Z0-9.\-=^]{0,14}$")
_LIQUID_PRIORITY = [
    "NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "GOOG", "AVGO", "TSLA",
    "BRK-B", "JPM", "LLY", "V", "MA", "NFLX", "XOM", "COST", "WMT", "UNH",
    "ORCL", "HD", "PG", "JNJ", "BAC", "ABBV", "KO", "PLTR", "AMD", "CRM",
    "CSCO", "PM", "CVX", "IBM", "ABT", "GE", "MCD", "LIN", "MRK", "WFC",
    "DIS", "NOW", "INTU", "AXP", "MS", "GS", "RTX", "CAT", "T", "VZ",
    "QCOM", "TXN", "AMAT", "MU", "LRCX", "PANW", "ADBE", "SHOP", "PEP",
]


class UniverseBuilder:
    def __init__(self, client: OpenAliceClient):
        self.client = client
        self.cfg = get_config()

    async def build(self, directive: str, asset_class: str | None = None) -> list[str]:
        directive = (directive or "").strip()
        asset_class = asset_class or self._infer_asset_class(directive)

        # Index/ETF presets expand to component companies. The scanner's job is
        # to find investable company ideas, not forecast SPY or ^GSPC directly.
        if asset_class == "index":
            symbols, etfs = await expand_index_directive(directive)
            if symbols:
                symbols = _prioritize_for_local(symbols)
                logger.info("Index universe %s expanded via %s -> %d companies",
                            directive or "world", ", ".join(etfs), len(symbols))
                cap = self.cfg.max_index_components_local
                if cap > 0 and len(symbols) > cap:
                    logger.info(
                        "Local index safety cap: %d/%d companies "
                        "(MAX_INDEX_COMPONENTS_LOCAL; set 0 for uncapped)",
                        cap, len(symbols),
                    )
                    symbols = symbols[:cap]
                return symbols[: self.cfg.max_universe_size]
            logger.warning("Index expansion failed for '%s'; falling back to broad equities",
                           directive)
            return self._seed_universe("equity")[: self.cfg.max_universe_size]

        if not directive:
            symbols = self._seed_universe(asset_class)
            logger.info("Empty directive -> seed universe (%d symbols)", len(symbols))
            return symbols[: self.cfg.max_universe_size]

        # If the directive is itself a list of tickers, use it directly.
        explicit = self._extract_explicit_symbols(directive)
        if explicit:
            logger.info("Directive parsed as explicit symbols: %s", explicit)
            return explicit[: self.cfg.max_universe_size]

        results = await self.client.search_symbols(directive, asset_class=asset_class)
        symbols = self._symbols_from_results(results)
        symbols = await self._validate_search_symbols(symbols)

        if not symbols:
            logger.warning(
                "Search for '%s' returned nothing — falling back to seed universe",
                directive,
            )
            symbols = self._seed_universe(asset_class)

        symbols = _dedupe(symbols)
        logger.info("Universe for '%s': %d symbols", directive, len(symbols))
        return symbols[: self.cfg.max_universe_size]

    async def _validate_search_symbols(self, symbols: list[str]) -> list[str]:
        """Filter OpenAlice search output to real tradeable Yahoo quote types."""
        symbols = _dedupe(symbols)
        if not symbols:
            return []

        resolved = await resolve_many(symbols)
        valid = [s for s in symbols if resolved.get(s, {}).get("valid", True)]
        dropped = [s for s in symbols if s not in valid]
        if dropped:
            logger.info(
                "Dropped %d non-tradeable search results: %s",
                len(dropped),
                ", ".join(dropped[:12]),
            )
        return valid

    # ── helpers ───────────────────────────────────────────────────────────
    @staticmethod
    def _infer_asset_class(directive: str) -> str:
        low = directive.lower()
        if any(h in low for h in _INDEX_HINTS):
            return "index"
        if any(h in low for h in _COMMODITY_HINTS):
            return "commodity"
        if any(h in low for h in _FOREX_HINTS):
            return "forex"
        if any(h in low for h in _CRYPTO_HINTS):
            return "crypto"
        return "equity"

    @staticmethod
    def _seed_universe(asset_class: str) -> list[str]:
        if asset_class == "crypto":
            return list(SEED_CRYPTO)
        if asset_class == "commodity":
            return list(SEED_COMMODITIES)
        if asset_class == "forex":
            return list(SEED_FOREX)
        # Broad sweep: equities plus a little crypto for breadth.
        return list(SEED_EQUITIES) + list(SEED_CRYPTO)

    @staticmethod
    def _extract_explicit_symbols(directive: str) -> list[str]:
        """Detect 'AAPL MSFT NVDA' / 'AAPL,MSFT' style directives."""
        raw_tokens = [t.strip() for t in re.split(r"[,\s]+", directive.strip()) if t.strip()]
        if not raw_tokens:
            return []
        # Avoid treating ordinary prose ("quality software") as tickers just
        # because it becomes all-caps after normalization.
        if not all(t == t.upper() or any(ch in t for ch in "^.-=") for t in raw_tokens):
            return []
        tokens = [t.upper() for t in raw_tokens]
        if all(_SYMBOL_RE.match(t) for t in tokens):
            return _dedupe(tokens)
        return []

    @staticmethod
    def _symbols_from_results(results: list[dict]) -> list[str]:
        out: list[str] = []
        for r in results:
            sym = (
                r.get("symbol") or r.get("ticker") or r.get("Symbol")
                or r.get("code") or r.get("id")
            )
            if isinstance(sym, str) and sym.strip():
                out.append(sym.strip().upper())
        return out


def _dedupe(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _prioritize_for_local(symbols: list[str]) -> list[str]:
    """Put highly liquid names first before applying a local safety cap."""
    original = _dedupe(symbols)
    present = set(original)
    out = [s for s in _LIQUID_PRIORITY if s in present]
    out.extend([s for s in original if s not in set(out)])
    return out
