"""Async MCP client for OpenAlice market-data tools.

Talks to OpenAlice's MCP server over streamable HTTP. The scanner never imports
OpenAlice TypeScript — all communication is the MCP protocol.

Design notes
------------
* On connect we call `list_tools()` and remember the real catalog. Each high
  level method resolves its intent to the first matching tool that actually
  exists, so the client survives upstream renames (e.g. the price-history tool
  name is not documented in the build plan).
* Every method degrades gracefully: on any failure it logs and returns an empty
  dict / list. The pipeline must continue when one symbol's data is missing.
"""

from __future__ import annotations

import json
import logging
from contextlib import AsyncExitStack
from typing import Any

logger = logging.getLogger("scanner.openalice")


class OpenAliceClient:
    """Open as an async context manager:

        async with OpenAliceClient(url) as oa:
            profile = await oa.get_profile("AAPL")
    """

    def __init__(self, mcp_url: str, use_cache: bool = True, offline: bool = False):
        self.mcp_url = mcp_url
        self.offline = offline
        self._stack: AsyncExitStack | None = None
        self.session: Any = None
        self.tool_names: set[str] = set()
        self._cache = None
        if use_cache:
            from scanner.cache import DiskCache
            self._cache = DiskCache("openalice", ttl_seconds=86_400)

    # ── lifecycle ─────────────────────────────────────────────────────────
    async def __aenter__(self) -> "OpenAliceClient":
        if self.offline:
            # No MCP connection: every tool call degrades to empty, and
            # get_ohlcv falls back to the free Stooq source.
            logger.info("OpenAlice client in OFFLINE mode (Stooq data only)")
            return self

        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        self._stack = AsyncExitStack()
        read, write, *_ = await self._stack.enter_async_context(
            streamablehttp_client(self.mcp_url)
        )
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()

        try:
            listed = await self.session.list_tools()
            self.tool_names = {t.name for t in listed.tools}
            logger.info("OpenAlice MCP connected — %d tools: %s",
                        len(self.tool_names), ", ".join(sorted(self.tool_names)))
        except Exception:  # noqa: BLE001
            logger.warning("Could not list OpenAlice tools; using documented names")
        return self

    async def __aexit__(self, *exc) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self.session = None

    # ── core call + parsing ───────────────────────────────────────────────
    def _resolve(self, candidates: list[str]) -> str | None:
        """First candidate tool name that the server actually exposes.

        If we never managed to list tools, optimistically return the first
        candidate and let the call fail gracefully.
        """
        if not self.tool_names:
            return candidates[0] if candidates else None
        for name in candidates:
            if name in self.tool_names:
                return name
        # Loose fallback: case-insensitive substring match.
        lowered = {n.lower(): n for n in self.tool_names}
        for name in candidates:
            if name.lower() in lowered:
                return lowered[name.lower()]
        return None

    async def _call(self, candidates: list[str], arguments: dict) -> Any:
        if self.offline:
            return None
        if self.session is None:
            logger.error("OpenAlice client used before connect")
            return None
        tool = self._resolve(candidates)
        if tool is None:
            logger.warning("No OpenAlice tool matched %s — skipping", candidates)
            return None
        try:
            result = await self.session.call_tool(tool, arguments=arguments)
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenAlice tool %s failed (%s): %s", tool, arguments, exc)
            return None
        return self._extract(result)

    @staticmethod
    def _extract(result: Any) -> Any:
        """Pull a JSON/text payload out of an MCP CallToolResult."""
        # Prefer structured content when the server provides it.
        structured = getattr(result, "structuredContent", None)
        if structured:
            return structured

        content = getattr(result, "content", None) or []
        texts: list[str] = []
        for block in content:
            text = getattr(block, "text", None)
            if text is not None:
                texts.append(text)
        if not texts:
            return None
        joined = "\n".join(texts)
        try:
            return json.loads(joined)
        except (json.JSONDecodeError, TypeError):
            return joined  # plain text (e.g. news blurbs)

    # ── high-level API ────────────────────────────────────────────────────
    async def search_symbols(self, query: str, asset_class: str = "equity") -> list[dict]:
        data = await self._call(
            ["marketSearchForResearch", "marketSearch"],
            {"query": query, "assetClass": asset_class},
        )
        return _as_list(data)

    async def get_profile(self, symbol: str) -> dict:
        return await self._cached_dict("profile", symbol, ["equityGetProfile"],
                                       {"symbol": symbol})

    async def get_financials(self, symbol: str) -> dict:
        return await self._cached_dict("financials", symbol, ["equityGetFinancials"],
                                       {"symbol": symbol})

    async def get_ratios(self, symbol: str) -> dict:
        return await self._cached_dict("ratios", symbol, ["equityGetRatios"],
                                       {"symbol": symbol})

    async def get_earnings_calendar(self, symbol: str) -> dict:
        return await self._cached_dict("earnings", symbol, ["equityGetEarningsCalendar"],
                                       {"symbol": symbol})

    async def _cached_dict(self, ns: str, symbol: str, candidates: list[str], args: dict) -> dict:
        key = f"{ns}:{symbol}"
        if self._cache is not None:
            hit = self._cache.get(key)
            if hit is not None:
                return hit
        data = _as_dict(await self._call(candidates, args))
        if self._cache is not None and data:
            self._cache.set(key, data)
        return data

    async def get_analyst_estimates(self, symbol: str) -> dict:
        return _as_dict(await self._call(
            ["equityGetAnalystEstimates"], {"symbol": symbol}))

    async def get_insider_trading(self, symbol: str) -> dict:
        return _as_dict(await self._call(
            ["equityGetInsiderTrading"], {"symbol": symbol}))

    async def calculate_indicator(self, asset: str, formula: str) -> dict:
        data = await self._call(
            ["calculateIndicator"], {"asset": asset, "formula": formula})
        return _as_dict(data)

    async def get_news(self, query: str, limit: int = 5) -> list[dict]:
        data = await self._call(
            ["grepNews", "globNews"], {"query": query, "limit": limit})
        return _as_list(data)

    async def get_ohlcv(self, symbol: str, interval: str = "1d", bars: int = 450) -> list[dict]:
        """Price history for Kronos. The exact tool name is not documented in
        the build plan, so we try several plausible names."""
        data = await self._call(
            [
                "equityGetPriceHistory",
                "marketGetCandles",
                "equityGetCandles",
                "marketGetPriceHistory",
                "getOhlcv",
                "priceHistory",
            ],
            {"symbol": symbol, "interval": interval, "bars": bars, "limit": bars},
        )
        rows = _as_list(data)
        candles = [_normalise_candle(r) for r in rows if isinstance(r, dict)]
        if candles:
            return candles
        # Free fallback (Stooq) so index/crypto scans work without OpenAlice.
        from scanner.config import get_config
        if get_config().use_data_fallback:
            from scanner.market_data import fallback_ohlcv
            return await fallback_ohlcv(symbol, bars=bars)
        return candles

    # ── portfolio / macro / integration ───────────────────────────────────
    async def get_positions(self) -> list[dict]:
        """Current portfolio holdings. Normalised to {symbol, qty, ...}."""
        data = await self._call(
            ["currentPositions", "allPositions", "getPositions", "portfolioPositions"],
            {},
        )
        out = []
        for row in _as_list(data):
            sym = row.get("symbol") or row.get("ticker") or row.get("asset")
            if isinstance(sym, str) and sym.strip():
                out.append({
                    "symbol": sym.strip().upper(),
                    "qty": row.get("qty") or row.get("quantity") or row.get("shares"),
                    "avg_price": row.get("avgPrice") or row.get("averagePrice"),
                    "market_value": row.get("marketValue") or row.get("value"),
                    "raw": row,
                })
        return out

    async def get_macro(self, series: list[str]) -> dict:
        """Latest value for each FRED/BLS series id (best effort)."""
        out: dict[str, float] = {}
        for s in series:
            data = await self._call(
                ["economyFredSearch", "economyBlsSearch", "macroSearch"],
                {"query": s, "seriesId": s, "id": s},
            )
            val = _latest_macro_value(data)
            if val is not None:
                out[s] = val
        return out

    async def push_inbox(self, title: str, markdown: str, payload: dict | None = None) -> bool:
        """Push a research note to OpenAlice's Inbox. Falls back to the HTTP
        event-ingest endpoint if no MCP inbox tool is exposed."""
        data = await self._call(
            ["inbox_push", "inboxPush", "pushInbox"],
            {"title": title, "body": markdown, "markdown": markdown,
             "payload": payload or {}},
        )
        if data is not None:
            return True
        return await self._ingest_event_http(title, markdown, payload or {})

    async def _ingest_event_http(self, title: str, summary: str, payload: dict) -> bool:
        import httpx
        from scanner.config import get_config
        url = get_config().openalice_backend_url.rstrip("/") + "/api/events/ingest"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(url, json={
                    "type": "scanner.complete",
                    "payload": {"title": title, "summary": summary, **payload},
                })
            return r.status_code < 400
        except Exception as exc:  # noqa: BLE001
            logger.warning("Inbox HTTP ingest failed: %s", exc)
            return False

    async def stage_order(self, symbol: str, side: str, qty: float,
                          entry: float | None = None, stop: float | None = None,
                          target: float | None = None) -> dict:
        """Stage (NOT execute) an order in OpenAlice for human approval.

        OpenAlice's stagePlaceOrder creates a pending order the user must
        confirm in the UI. This never executes a trade on its own.
        """
        data = await self._call(["stagePlaceOrder"], {
            "symbol": symbol, "side": side, "qty": qty, "quantity": qty,
            "type": "limit", "limitPrice": entry, "entry": entry,
            "stopLoss": stop, "takeProfit": target, "staged": True,
        })
        return _as_dict(data)


# ── module-level coercion helpers ─────────────────────────────────────────
def _as_dict(data: Any) -> dict:
    if isinstance(data, dict):
        # Some tools wrap the payload, e.g. {"data": {...}} or {"result": {...}}.
        for key in ("data", "result", "profile"):
            inner = data.get(key)
            if isinstance(inner, dict):
                return inner
        return data
    return {}


def _as_list(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("results", "data", "items", "symbols", "candles", "news"):
            inner = data.get(key)
            if isinstance(inner, list):
                return [x for x in inner if isinstance(x, dict)]
    return []


def _normalise_candle(row: dict) -> dict:
    """Map a price-history row to {ts, open, high, low, close, volume}."""
    def pick(*keys, default=None):
        for k in keys:
            if k in row and row[k] is not None:
                return row[k]
        return default

    return {
        "ts": pick("ts", "timestamp", "timestamps", "date", "time"),
        "open": pick("open", "o", "Open"),
        "high": pick("high", "h", "High"),
        "low": pick("low", "l", "Low"),
        "close": pick("close", "c", "Close", "adjClose"),
        "volume": pick("volume", "v", "Volume", default=0.0),
    }


def _latest_macro_value(data: Any) -> float | None:
    """Pull the most recent numeric observation from a FRED/BLS response."""
    if data is None:
        return None
    if isinstance(data, (int, float)):
        return float(data)
    if isinstance(data, dict):
        for k in ("value", "latest", "last"):
            if isinstance(data.get(k), (int, float)):
                return float(data[k])
        for k in ("observations", "data", "series", "values"):
            seq = data.get(k)
            if isinstance(seq, list) and seq:
                return _latest_macro_value(seq[-1])
    if isinstance(data, list) and data:
        return _latest_macro_value(data[-1])
    return None
