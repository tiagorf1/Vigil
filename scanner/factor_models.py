"""Theory-grounded fundamental factor frameworks.

These are reputable, public *methods* (not proprietary scores) that encode how
quant-value investors actually judge a company:

* Piotroski F-score (2000)   — 9-point accounting-quality test, year over year.
* Greenblatt Magic Formula   — earnings yield + return on capital (approximated
                               from the snapshot we have; flagged as such).
* Graham defensive criteria  — the classic value checklist.

Each returns a structured breakdown AND contributes to a single 0-100
`framework_score`, which `fundamentals.score()` blends into the methodology
score. Everything degrades gracefully: a check whose input is missing is simply
dropped and the denominator shrinks, so a name with no history still gets a fair
Graham/Greenblatt read.
"""

from __future__ import annotations


def _num(v):
    return v if isinstance(v, (int, float)) else None


# ── Piotroski F-score (needs current + prior-year ratio dicts) ──────────────
def piotroski(curr: dict, prior: dict) -> dict:
    """Each input dict may contain: roa, fcf, ni, gross_margin, asset_turnover,
    leverage (LT debt / assets), current_ratio, shares. Missing inputs drop the
    corresponding check. Returns {score, max, checks{name: bool}}."""
    checks: dict[str, bool] = {}

    def add(name, cond):
        if cond is not None:
            checks[name] = bool(cond)

    roa, fcf, ni = _num(curr.get("roa")), _num(curr.get("fcf")), _num(curr.get("ni"))
    roa0 = _num(prior.get("roa"))
    # Profitability
    add("roa_positive", roa > 0 if roa is not None else None)
    add("cfo_positive", fcf > 0 if fcf is not None else None)
    add("roa_rising", (roa > roa0) if (roa is not None and roa0 is not None) else None)
    # Accruals: cash flow backs earnings (FCF proxy for CFO).
    add("accruals_ok", (fcf > ni) if (fcf is not None and ni is not None) else None)
    # Leverage / liquidity
    lev, lev0 = _num(curr.get("leverage")), _num(prior.get("leverage"))
    add("leverage_falling", (lev < lev0) if (lev is not None and lev0 is not None) else None)
    cr, cr0 = _num(curr.get("current_ratio")), _num(prior.get("current_ratio"))
    add("current_ratio_rising", (cr > cr0) if (cr is not None and cr0 is not None) else None)
    sh, sh0 = _num(curr.get("shares")), _num(prior.get("shares"))
    add("no_dilution", (sh <= sh0 * 1.01) if (sh is not None and sh0 is not None) else None)
    # Operating efficiency
    gm, gm0 = _num(curr.get("gross_margin")), _num(prior.get("gross_margin"))
    add("gross_margin_rising", (gm > gm0) if (gm is not None and gm0 is not None) else None)
    at, at0 = _num(curr.get("asset_turnover")), _num(prior.get("asset_turnover"))
    add("asset_turnover_rising", (at > at0) if (at is not None and at0 is not None) else None)

    score = sum(1 for v in checks.values() if v)
    return {"score": score, "max": len(checks), "checks": checks}


# ── Greenblatt Magic Formula (approximate from snapshot) ────────────────────
def greenblatt(m: dict) -> dict:
    """Earnings yield (EBIT/EV proxy) and return on capital (ROC proxy). We don't
    have full EV/invested-capital, so we approximate: earnings yield from the
    inverse P/E, ROC from ROA/operating efficiency. Flagged approximate."""
    pe = _num(m.get("forward_pe")) or _num(m.get("trailing_pe"))
    earnings_yield = round(1.0 / pe, 4) if (pe and pe > 0) else None
    # ROC proxy: prefer ROIC-like ROA; fall back to operating_margin * turnover.
    roc = _num(m.get("roa"))
    if roc is None:
        om = _num(m.get("operating_margin"))
        roc = om  # weakest proxy
    signal = None
    if earnings_yield is not None and roc is not None:
        # Both cheap (high earnings yield) and high-quality (high ROC) -> strong.
        ey_ok = earnings_yield >= 0.06
        roc_ok = roc >= 0.10
        signal = 1.0 if (ey_ok and roc_ok) else (0.5 if (ey_ok or roc_ok) else 0.0)
    return {"earnings_yield": earnings_yield, "roc": round(roc, 4) if roc is not None else None,
            "signal": signal, "approximate": True}


# ── Graham defensive checklist ──────────────────────────────────────────────
def graham(m: dict) -> dict:
    checks: dict[str, bool] = {}

    def add(name, cond):
        if cond is not None:
            checks[name] = bool(cond)

    pe = _num(m.get("forward_pe")) or _num(m.get("trailing_pe"))
    pb = _num(m.get("pb"))
    add("earnings_positive", (pe > 0) if pe is not None else None)
    add("current_ratio_2x", (_num(m.get("current_ratio")) >= 2.0)
        if _num(m.get("current_ratio")) is not None else None)
    add("pe_le_15", (0 < pe <= 15) if pe is not None else None)
    add("pb_le_1_5", (0 < pb <= 1.5) if pb is not None else None)
    if pe is not None and pb is not None and pe > 0 and pb > 0:
        add("graham_number", pe * pb <= 22.5)
    add("pays_dividend", (_num(m.get("dividend_yield")) or 0) > 0
        if m.get("dividend_yield") is not None else None)
    add("earnings_growth_pos", (_num(m.get("earnings_growth")) > 0)
        if _num(m.get("earnings_growth")) is not None else None)
    add("low_debt", (_num(m.get("debt_to_equity")) < 1.0)
        if _num(m.get("debt_to_equity")) is not None else None)

    passed = sum(1 for v in checks.values() if v)
    return {"passed": passed, "total": len(checks), "checks": checks}


# ── orchestrator ────────────────────────────────────────────────────────────
def evaluate(m: dict, curr: dict | None = None, prior: dict | None = None) -> dict:
    """Combine the three frameworks into one 0-100 framework_score (weighted over
    whatever is available) plus the per-framework detail."""
    g = graham(m)
    gb = greenblatt(m)
    pio = piotroski(curr or {}, prior or {}) if (curr and prior) else {"score": 0, "max": 0, "checks": {}}

    parts: list[tuple[float, float]] = []   # (value 0-1, weight)
    if pio["max"] >= 4:                       # only trust Piotroski with enough checks
        parts.append((pio["score"] / pio["max"], 0.5))
    if g["total"] >= 3:
        parts.append((g["passed"] / g["total"], 0.3))
    if gb["signal"] is not None:
        parts.append((gb["signal"], 0.2))

    available = bool(parts)
    if available:
        wsum = sum(w for _, w in parts)
        framework_score = round(100 * sum(v * w for v, w in parts) / wsum, 1)
    else:
        framework_score = None

    return {"available": available, "framework_score": framework_score,
            "piotroski": pio, "graham": g, "greenblatt": gb}
