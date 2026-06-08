"""All the Yahoo Finance endpoints, in one place — maximum free information.

Disk/RAM: tiny. These are just HTTP calls; responses are cached as small JSON
files under .cache/yahoo (daily TTL; intraday/options not cached). No bulk
datasets are stored locally.

Endpoints:
  intraday()                1m/5m bars  -> short-horizon Kronos forecasts
  fundamentals_timeseries() historical financials (KEYLESS) -> trends
  options_chain()           implied vol, strikes, OI -> options + vol edge
  insights()                Yahoo's technical events, S/R, valuation flags
  recommendations()         peer tickers -> pairs / sector-relative
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("scanner.yahoo")

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Vigil/1.0"
_H = {"User-Agent": _UA}


def _cache(ns: str, ttl: int):
    try:
        from scanner.cache import DiskCache
        return DiskCache(f"yahoo_{ns}", ttl_seconds=ttl)
    except Exception:  # noqa: BLE001
        return None


async def _get(url: str, params: dict | None = None, crumb: bool = False):
    headers = dict(_H)
    cookies = {}
    par = dict(params or {})
    if crumb:
        from scanner.fundamentals import _state, _refresh_crumb
        if not _state.get("crumb"):
            await _refresh_crumb()
        par["crumb"] = _state.get("crumb")
        cookies = _state.get("cookies") or {}
    try:
        async with httpx.AsyncClient(timeout=15, headers=headers, cookies=cookies,
                                     follow_redirects=True) as c:
            r = await c.get(url, params=par)
        if r.status_code == 200:
            return r.json()
    except Exception as exc:  # noqa: BLE001
        logger.debug("yahoo GET failed %s: %s", url, exc)
    return None


# ── intraday bars (short-horizon) ──────────────────────────────────────────
async def intraday(symbol: str, interval: str = "5m", rng: str = "5d") -> list[dict]:
    d = await _get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                   {"range": rng, "interval": interval})
    try:
        res = d["chart"]["result"][0]
        ts = res["timestamp"]; q = res["indicators"]["quote"][0]
        import datetime as _dt
        out = []
        for i in range(len(ts)):
            if None in (q["open"][i], q["high"][i], q["low"][i], q["close"][i]):
                continue
            out.append({"ts": _dt.datetime.utcfromtimestamp(ts[i]).isoformat(),
                        "open": q["open"][i], "high": q["high"][i], "low": q["low"][i],
                        "close": q["close"][i], "volume": q["volume"][i] or 0})
        return out
    except (KeyError, IndexError, TypeError):
        return []


# ── historical fundamentals (keyless) ──────────────────────────────────────
async def fundamentals_timeseries(symbol: str) -> dict:
    cache = _cache("fts", 86_400)
    if cache and (hit := cache.get(symbol)) is not None:
        return hit
    types = ("annualTotalRevenue,annualNetIncome,annualGrossProfit,"
             "annualOperatingIncome,annualDilutedEPS,annualTotalAssets,"
             "annualStockholdersEquity,annualFreeCashFlow,annualLongTermDebt,"
             "annualCurrentAssets,annualCurrentLiabilities,annualShareIssued")
    d = await _get(f"https://query2.finance.yahoo.com/ws/fundamentals-timeseries/"
                   f"v1/finance/timeseries/{symbol}",
                   {"type": types, "period1": "1483228800", "period2": "1900000000"})
    out = {}
    for row in (d or {}).get("timeseries", {}).get("result", []) if d else []:
        meta = row.get("meta", {})
        key = (meta.get("type") or [""])[0]
        series = row.get(key) or []
        vals = [(p.get("asOfDate"), (p.get("reportedValue") or {}).get("raw"))
                for p in series if p]
        if key and vals:
            out[key.replace("annual", "").lower()] = vals
    if cache and out:
        cache.set(symbol, out)
    return out


# ── options chain -> implied vol + expected move ───────────────────────────
async def options_chain(symbol: str) -> dict:
    d = await _get(f"https://query2.finance.yahoo.com/v7/finance/options/{symbol}",
                   crumb=True)
    try:
        res = d["optionChain"]["result"][0]
        spot = res["quote"].get("regularMarketPrice")
        opt = (res.get("options") or [{}])[0]
        calls, puts = opt.get("calls", []), opt.get("puts", [])
        def atm(rows):
            if not rows or not spot:
                return None
            r = min(rows, key=lambda x: abs((x.get("strike") or 0) - spot))
            return r
        ac, ap = atm(calls), atm(puts)
        ivs = [x.get("impliedVolatility") for x in (ac, ap) if x and x.get("impliedVolatility")]
        atm_iv = sum(ivs) / len(ivs) if ivs else None
        straddle = ((ac or {}).get("lastPrice") or 0) + ((ap or {}).get("lastPrice") or 0)
        exp_move = (straddle / spot * 100) if spot else None
        coi = sum(x.get("openInterest") or 0 for x in calls)
        poi = sum(x.get("openInterest") or 0 for x in puts)
        return {"spot": spot, "atm_iv": atm_iv, "expected_move_pct": round(exp_move, 2) if exp_move else None,
                "expirations": len(res.get("expirationDates", [])),
                "call_oi": coi, "put_oi": poi,
                "put_call_oi_ratio": round(poi / coi, 2) if coi else None,
                "has_options": bool(calls or puts)}
    except (KeyError, IndexError, TypeError):
        return {"has_options": False}


# ── insights (Yahoo's own technical + valuation flags) ─────────────────────
async def insights(symbol: str) -> dict:
    d = await _get("https://query1.finance.yahoo.com/ws/insights/v2/finance/insights",
                   {"symbol": symbol})
    try:
        r = d["finance"]["result"]
        ti = (r.get("instrumentInfo") or {}).get("technicalEvents") or {}
        val = (r.get("instrumentInfo") or {}).get("valuation") or {}
        kt = r.get("keyTechnicals") or {}
        return {
            "short_term": (ti.get("shortTermOutlook") or {}).get("direction"),
            "intermediate_term": (ti.get("intermediateTermOutlook") or {}).get("direction"),
            "long_term": (ti.get("longTermOutlook") or {}).get("direction"),
            "valuation": val.get("description"),
            "support": kt.get("support"), "resistance": kt.get("resistance"),
            "stop_loss": kt.get("stopLoss"),
        }
    except (KeyError, IndexError, TypeError):
        return {}


# ── peers / similar tickers ────────────────────────────────────────────────
async def recommendations(symbol: str) -> list[str]:
    cache = _cache("peers", 7 * 86_400)
    if cache and (hit := cache.get(symbol)) is not None:
        return hit
    d = await _get(f"https://query2.finance.yahoo.com/v6/finance/recommendationsbysymbol/{symbol}")
    try:
        peers = [x.get("symbol") for x in d["finance"]["result"][0]["recommendedSymbols"]]
        peers = [p for p in peers if p]
        if cache and peers:
            cache.set(symbol, peers)
        return peers
    except (KeyError, IndexError, TypeError):
        return []
