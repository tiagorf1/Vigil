"""Real fundamentals — a reliable, normalized source + a methodology score.

Why this exists: the old fundamental screen scored on *guessed* OpenAlice field
names, so factors silently missed and the score was a flat "puppet" even with
OpenAlice live; offline it was blank. This module instead pulls a normalized set
of fundamentals from Yahoo's quoteSummary (free, no key, works offline) and
scores them the way an analyst would: valuation, growth, profitability, balance
sheet health, and an analyst tilt. Returns the score AND a factor breakdown so
the report can explain it.
"""

from __future__ import annotations

import logging

import httpx

from scanner.config import get_config

logger = logging.getLogger("scanner.fundamentals")

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Vigil/1.0"
_MODULES = ("financialData,defaultKeyStatistics,summaryDetail,assetProfile,"
            "price,earningsTrend")
_HOSTS = ("query2.finance.yahoo.com", "query1.finance.yahoo.com")
_state: dict = {"crumb": None, "cookies": None}


def _raw(o, k):
    if not isinstance(o, dict):
        return None
    v = o.get(k)
    if isinstance(v, dict):
        return v.get("raw")
    return v


async def _refresh_crumb() -> None:
    async with httpx.AsyncClient(timeout=12, headers={"User-Agent": _UA},
                                 follow_redirects=True) as c:
        try:
            await c.get("https://fc.yahoo.com")
        except Exception:  # noqa: BLE001
            pass
        r = await c.get("https://query2.finance.yahoo.com/v1/test/getcrumb")
        _state["crumb"] = (r.text or "").strip()
        _state["cookies"] = dict(c.cookies)


async def _quote_summary(symbol: str) -> dict | None:
    if not _state["crumb"]:
        await _refresh_crumb()
    for attempt in range(2):
        for host in _HOSTS:
            url = f"https://{host}/v10/finance/quoteSummary/{symbol}"
            try:
                async with httpx.AsyncClient(timeout=12, headers={"User-Agent": _UA},
                                             cookies=_state["cookies"] or {},
                                             follow_redirects=True) as c:
                    r = await c.get(url, params={"modules": _MODULES,
                                                 "crumb": _state["crumb"]})
            except Exception as exc:  # noqa: BLE001
                logger.debug("quoteSummary %s via %s failed: %s", symbol, host, exc)
                continue
            if r.status_code == 200:
                try:
                    res = r.json()["quoteSummary"]["result"]
                    return res[0] if res else None
                except Exception:  # noqa: BLE001
                    return None
            if r.status_code in (401, 403):
                await _refresh_crumb()
                break  # retry both hosts with fresh crumb
    return None


def _normalize(m: dict) -> None:
    """Consistent units (debt/equity as a ratio x, not %) + clean rounding."""
    de = m.get("debt_to_equity")
    if isinstance(de, (int, float)) and de > 5:   # Yahoo reports D/E as a percent
        m["debt_to_equity"] = de / 100.0
    for k in ("trailing_pe", "forward_pe", "peg", "pb", "ps", "current_ratio",
              "quick_ratio", "debt_to_equity"):
        if isinstance(m.get(k), (int, float)):
            m[k] = round(m[k], 2)
    for k in ("profit_margin", "operating_margin", "gross_margin", "roe", "roa",
              "revenue_growth", "earnings_growth", "dividend_yield", "rev_cagr_3y",
              "margin_trend"):
        if isinstance(m.get(k), (int, float)):
            m[k] = round(m[k], 4)


async def fetch(symbol: str, use_cache: bool = True) -> dict:
    """Normalized fundamentals dict (empty if unavailable).

    Provider order: FMP (richer: history, sector medians) when FMP_API_KEY is set,
    else Yahoo quoteSummary (free, no key). Same normalized schema either way.
    """
    cfg = get_config()
    cache = None
    if use_cache:
        try:
            from scanner.cache import DiskCache
            cache = DiskCache("fundamentals", ttl_seconds=86_400)
            hit = cache.get(f"f:{symbol}")
            if hit is not None:
                return hit
        except Exception:  # noqa: BLE001
            cache = None

    # Preferred: Financial Modeling Prep (historical statements + ratios).
    if cfg.fundamentals_provider in ("auto", "fmp") and cfg.fmp_api_key:
        fm = await _fmp_fetch(symbol, cfg.fmp_api_key)
        if fm and fm.get("current_price"):
            _normalize(fm)
            await _enrich_frameworks(fm, symbol)
            if cache is not None:
                cache.set(f"f:{symbol}", fm)
            return fm

    d = await _quote_summary(symbol)
    if not d:
        return {}
    fd = d.get("financialData", {}); ks = d.get("defaultKeyStatistics", {})
    sd = d.get("summaryDetail", {}); ap = d.get("assetProfile", {})
    pr = d.get("price", {})
    m = {
        "name": _raw(pr, "longName") or _raw(pr, "shortName"),
        "sector": ap.get("sector") or "",
        "industry": ap.get("industry") or "",
        "market_cap": _raw(pr, "marketCap") or _raw(sd, "marketCap"),
        "trailing_pe": _raw(sd, "trailingPE"),
        "forward_pe": _raw(sd, "forwardPE") or _raw(ks, "forwardPE"),
        "peg": _raw(ks, "pegRatio") or _raw(ks, "trailingPegRatio"),
        "pb": _raw(ks, "priceToBook"),
        "ps": _raw(sd, "priceToSalesTrailing12Months"),
        "profit_margin": _raw(fd, "profitMargins") or _raw(ks, "profitMargins"),
        "operating_margin": _raw(fd, "operatingMargins"),
        "gross_margin": _raw(fd, "grossMargins"),
        "roe": _raw(fd, "returnOnEquity"),
        "roa": _raw(fd, "returnOnAssets"),
        "revenue_growth": _raw(fd, "revenueGrowth"),
        "earnings_growth": _raw(fd, "earningsGrowth") or _raw(fd, "earningsQuarterlyGrowth"),
        "debt_to_equity": _raw(fd, "debtToEquity"),
        "current_ratio": _raw(fd, "currentRatio"),
        "quick_ratio": _raw(fd, "quickRatio"),
        "free_cashflow": _raw(fd, "freeCashflow"),
        "total_cash": _raw(fd, "totalCash"),
        "recommendation": fd.get("recommendationKey") if isinstance(fd, dict) else None,
        "target_mean": _raw(fd, "targetMeanPrice"),
        "current_price": _raw(fd, "currentPrice") or _raw(pr, "regularMarketPrice"),
        "dividend_yield": _raw(sd, "dividendYield"),
    }
    # Estimate-revision momentum (one of the more predictive fundamental signals):
    # net analyst EPS upgrades vs downgrades over the last 30 days.
    up = dn = 0
    for t in (d.get("earningsTrend", {}) or {}).get("trend", []) or []:
        rev = t.get("epsRevisions") or {}
        up += (_raw(rev, "upLast30days") or 0) or 0
        dn += (_raw(rev, "downLast30days") or 0) or 0
    m["rev_up_30"] = up
    m["rev_down_30"] = dn
    m["rev_net_30"] = up - dn
    _normalize(m)
    await _enrich_frameworks(m, symbol)
    if cache is not None and m.get("current_price"):
        cache.set(f"f:{symbol}", m)
    return m


def _n(v):
    return v if isinstance(v, (int, float)) else None


async def _framework_inputs(symbol: str) -> tuple[dict, dict]:
    """Build (current, prior) ratio dicts for Piotroski from Yahoo's keyless
    fundamentals-timeseries. Returns ({}, {}) when history is unavailable."""
    try:
        from scanner import yahoo
        ts = await yahoo.fundamentals_timeseries(symbol)
    except Exception:  # noqa: BLE001
        return {}, {}
    if not ts:
        return {}, {}
    by_year: dict[str, dict] = {}
    for key, series in ts.items():
        for date, val in series:
            if date is None or val is None:
                continue
            by_year.setdefault(str(date)[:4], {})[key] = val
    years = sorted(by_year)
    if len(years) < 2:
        return {}, {}

    def ratios(y: str) -> dict:
        d = by_year[y]
        assets = _n(d.get("totalassets")); rev = _n(d.get("totalrevenue"))
        cl = _n(d.get("currentliabilities")); ca = _n(d.get("currentassets"))
        ni = _n(d.get("netincome")); gp = _n(d.get("grossprofit"))
        ltd = _n(d.get("longtermdebt"))
        return {
            "ni": ni, "fcf": _n(d.get("freecashflow")),
            "roa": (ni / assets) if (ni is not None and assets) else None,
            "gross_margin": (gp / rev) if (gp is not None and rev) else None,
            "asset_turnover": (rev / assets) if (rev is not None and assets) else None,
            "leverage": (ltd / assets) if (ltd is not None and assets) else None,
            "current_ratio": (ca / cl) if (ca is not None and cl) else None,
            "shares": _n(d.get("shareissued")),
        }
    return ratios(years[-1]), ratios(years[-2])


async def _enrich_frameworks(m: dict, symbol: str) -> None:
    """Attach m['_frameworks'] (Piotroski / Greenblatt / Graham). Best-effort."""
    try:
        from scanner import factor_models
        curr, prior = await _framework_inputs(symbol)
        fr = factor_models.evaluate(m, curr, prior)
        if fr.get("available") or fr.get("graham", {}).get("total"):
            m["_frameworks"] = fr
    except Exception as exc:  # noqa: BLE001
        logger.debug("framework eval failed for %s: %s", symbol, exc)


async def _fmp_fetch(symbol: str, key: str) -> dict:
    """Financial Modeling Prep — TTM ratios + 4y income statements for trends."""
    base = "https://financialmodelingprep.com/api/v3"
    try:
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": _UA}) as c:
            async def get(path, **params):
                params["apikey"] = key
                r = await c.get(f"{base}/{path}", params=params)
                j = r.json() if r.status_code == 200 else None
                return j if isinstance(j, list) else None
            prof = await get(f"profile/{symbol}")
            rat = await get(f"ratios-ttm/{symbol}")
            inc = await get(f"income-statement/{symbol}", period="annual", limit=4)
    except Exception as exc:  # noqa: BLE001
        logger.debug("FMP fetch failed for %s: %s", symbol, exc)
        return {}
    if not prof:
        return {}
    p = prof[0]
    r0 = (rat or [{}])[0]
    m = {
        "name": p.get("companyName"), "sector": p.get("sector") or "",
        "industry": p.get("industry") or "", "market_cap": p.get("mktCap"),
        "current_price": p.get("price"), "beta": p.get("beta"),
        "trailing_pe": r0.get("peRatioTTM"), "forward_pe": None,
        "peg": r0.get("pegRatioTTM"), "pb": r0.get("priceToBookRatioTTM"),
        "ps": r0.get("priceToSalesRatioTTM"),
        "profit_margin": r0.get("netProfitMarginTTM"),
        "operating_margin": r0.get("operatingProfitMarginTTM"),
        "gross_margin": r0.get("grossProfitMarginTTM"),
        "roe": r0.get("returnOnEquityTTM"), "roa": r0.get("returnOnAssetsTTM"),
        "debt_to_equity": r0.get("debtEquityRatioTTM"),
        "current_ratio": r0.get("currentRatioTTM"),
        "quick_ratio": r0.get("quickRatioTTM"),
        "dividend_yield": r0.get("dividendYielTTM"),
        "recommendation": None, "target_mean": None,
        "rev_net_30": None, "source": "fmp",
    }
    # Trends from the income-statement history (newest first).
    if inc and len(inc) >= 2:
        rev = [x.get("revenue") for x in inc]
        ni = [x.get("netIncome") for x in inc]
        if rev[0] and rev[1]:
            m["revenue_growth"] = rev[0] / rev[1] - 1
        if ni[0] and ni[1]:
            m["earnings_growth"] = ni[0] / ni[1] - 1
        if len(inc) >= 4 and rev[3] and rev[0] and rev[3] > 0:
            m["rev_cagr_3y"] = (rev[0] / rev[3]) ** (1 / 3) - 1
        if rev[0] and rev[-1] and ni[0] is not None and ni[-1] is not None:
            m["margin_trend"] = (ni[0] / rev[0]) - (ni[-1] / rev[-1])
    return m


# ── methodology score (0-100) + factor breakdown ──────────────────────────
def score(m: dict) -> tuple[float, dict]:
    if not m:
        return 0.0, {"valuation": 0, "growth": 0, "profitability": 0, "health": 0, "analyst": 0}

    def band(v, table, default=0.0):
        if not isinstance(v, (int, float)):
            return default
        for thr, pts in table:
            if v <= thr:
                return pts
        return table[-1][1]

    # Valuation (max 26) - cheaper is better. Penalize losses (no/again. PE<=0).
    val = 0.0
    pe = m.get("forward_pe") or m.get("trailing_pe")
    if isinstance(pe, (int, float)) and pe > 0:
        val += band(pe, [(12, 12), (20, 9), (30, 5), (45, 2)], 0)
    peg = m.get("peg")
    if isinstance(peg, (int, float)) and peg > 0:
        val += band(peg, [(1.0, 8), (1.5, 6), (2.5, 3)], 0)
    pb = m.get("pb")
    if isinstance(pb, (int, float)) and pb > 0:
        val += band(pb, [(2, 6), (5, 4), (10, 2)], 0)
    val = min(val, 26)

    # Growth (max 26)
    gr = 0.0
    rg = m.get("revenue_growth")
    if isinstance(rg, (int, float)):
        gr += band(rg, [(0, 0), (0.05, 5), (0.12, 9), (0.25, 13)], 13)
    eg = m.get("earnings_growth")
    if isinstance(eg, (int, float)):
        gr += band(eg, [(0, 0), (0.10, 7), (0.25, 13)], 13)
    gr = min(gr, 26)

    # Profitability (max 26)
    pf = 0.0
    pm = m.get("profit_margin")
    if isinstance(pm, (int, float)):
        pf += band(pm, [(0, 0), (0.05, 4), (0.12, 8), (0.20, 11)], 11)
    roe = m.get("roe")
    if isinstance(roe, (int, float)):
        pf += band(roe, [(0, 0), (0.08, 4), (0.15, 8), (0.30, 11)], 11)
    gm = m.get("gross_margin")
    if isinstance(gm, (int, float)) and gm > 0.4:
        pf += 4
    pf = min(pf, 26)

    # Balance-sheet health (max 22)
    he = 0.0
    de = m.get("debt_to_equity")   # normalized to a ratio (x), e.g. 0.8 = 0.8x
    if isinstance(de, (int, float)):
        he += band(de, [(0.4, 9), (0.9, 6), (1.6, 3), (2.6, 1)], 0)
    cr = m.get("current_ratio")
    if isinstance(cr, (int, float)):
        he += band(cr, [(1.0, 0), (1.5, 5), (3.0, 8)], 6)
    fcf = m.get("free_cashflow")
    if isinstance(fcf, (int, float)) and fcf > 0:
        he += 5
    he = min(he, 22)

    # Analyst tilt (max 10)
    an = 0.0
    rec = (m.get("recommendation") or "").lower()
    if rec in ("strong_buy", "buy"):
        an += 6
    elif rec in ("hold", "none", ""):
        an += 2
    tm, cp = m.get("target_mean"), m.get("current_price")
    if isinstance(tm, (int, float)) and isinstance(cp, (int, float)) and cp > 0:
        up = tm / cp - 1
        an += band(up, [(0, 0), (0.10, 2), (0.25, 4)], 4)
    an = min(an, 10)

    # Estimate-revision momentum (max 8): net EPS upgrades vs downgrades (30d).
    rev = 0.0
    net = m.get("rev_net_30")
    if isinstance(net, (int, float)):
        rev = band(net, [(-1, 0), (0, 3), (1, 5), (3, 8)], 8) if net > 0 else (3 if net == 0 else 0)
    rev = min(rev, 8)

    # Quality (max 8): Piotroski-lite — positive ROA, positive FCF, FCF backs
    # earnings (low accruals), healthy gross margin.
    q = 0.0
    if isinstance(m.get("roa"), (int, float)) and m["roa"] > 0:
        q += 2
    fcf = m.get("free_cashflow")
    if isinstance(fcf, (int, float)) and fcf > 0:
        q += 3
    if isinstance(m.get("gross_margin"), (int, float)) and m["gross_margin"] > 0.35:
        q += 2
    if isinstance(m.get("operating_margin"), (int, float)) and m["operating_margin"] > 0.10:
        q += 1
    q = min(q, 8)

    # Trend (max 6): multi-year revenue CAGR + improving net margin (FMP only).
    tr = 0.0
    cagr = m.get("rev_cagr_3y")
    if isinstance(cagr, (int, float)):
        tr += band(cagr, [(0, 0), (0.08, 2), (0.20, 4)], 4)
    mt = m.get("margin_trend")
    if isinstance(mt, (int, float)) and mt > 0:
        tr += 2
    tr = min(tr, 6)

    total = round(val + gr + pf + he + an + rev + q + tr, 1)
    breakdown = {"valuation": round(val, 1), "growth": round(gr, 1),
                 "profitability": round(pf, 1), "health": round(he, 1),
                 "analyst": round(an, 1), "revisions": round(rev, 1),
                 "quality": round(q, 1), "trend": round(tr, 1)}

    # Blend in the theory-grounded frameworks (Piotroski / Greenblatt / Graham)
    # when available: 82% bucket methodology + 18% framework consensus. Keeps the
    # detailed factor score primary while letting the classic frameworks move it.
    fr = m.get("_frameworks") or {}
    fs = fr.get("framework_score")
    if fr.get("available") and isinstance(fs, (int, float)):
        total = round(0.82 * total + 0.18 * fs, 1)
        breakdown["frameworks"] = round(fs, 1)

    return min(total, 100.0), breakdown
