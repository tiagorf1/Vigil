"""Report synthesis layer.

Takes everything collected for one symbol and produces the structured research
report. The LLM provider is pluggable via LLM_PROVIDER:

    gemini    — Google AI Studio (free tier), default
    anthropic — Claude (stronger synthesis)
    none      — deterministic template, no API key required

All three return the identical JSON schema; only the transport differs.
"""

from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel

from scanner.config import get_config

logger = logging.getLogger("scanner.report")

SYSTEM_PROMPT = """\
You are a rigorous financial analyst producing investment research for a sophisticated
individual investor. Your reports are precise, honest, and free of promotional language.

You will receive structured data for a single security: fundamentals, technicals,
performance metrics, a Kronos model price forecast, and recent news. Generate a
research report in JSON format.

Rules:
- Conviction score 1-5: only give 4-5 if the evidence is genuinely strong across
  multiple dimensions. 3 is the honest average. Be calibrated, not generous.
- The thesis must be YOUR synthesis - do not summarise the data. Say what it means.
  Write 2 to 3 full paragraphs covering: the setup, what the fundamentals and
  technicals together imply, what the Kronos forecast adds, and the key uncertainty.
- "reasons" must list 4 to 6 specific, concrete reasons this idea is interesting
  right now, each citing actual numbers from the data (a return, a level, a ratio,
  the forecast probability). No generic statements.
- "horizon" classifies the trade: "low" = short-term / day-trade-like / technically
  driven / higher volatility; "high" = long-term / fundamentally driven / lower
  volatility; "medium" = a multi-week swing in between. Choose based on the actual
  data, not the asset type.
- Entry/stop/target must be specific numbers derived from the ATR/volatility and the
  forecast range. Do not give vague ranges like "near current price".
- Risks must be specific to this name - not generic market risks.
- If the data is insufficient to form a view, say so in the thesis and give conviction 1.
- No em dashes. No exclamation marks. No corporate cliches.
- Output valid JSON only - no preamble, no markdown fences.
"""

CRITIC_SYSTEM = """\
You are a meticulous quantitative risk auditor reviewing an AUTOMATED trading pick
for INTERNAL COHERENCE and basic financial sense. You are NOT re-doing the
analysis — you are checking whether the computed numbers contradict each other or
violate elementary finance. Flag things like: a long with a bearish forecast (or a
short with a bullish one); a stop on the wrong side of entry; a risk/reward that
does not match the entry/stop/target; "high conviction" on a near-coin-flip
probability; a position size that ignores a missing edge; a horizon that fights the
thesis; or any claim unsupported by the supplied numbers. Be specific and terse.
Output ONLY JSON: {"coherent": bool, "severity": "low|medium|high",
"concerns": ["..."]}. Use severity "high" only for a problem that would change the
decision; "low" if it is essentially coherent."""

_REQUIRED_KEYS = [
    "symbol", "name", "conviction", "thesis", "reasons", "horizon",
    "fundamental_summary", "technical_summary", "forecast_summary", "entry_zone",
    "stop_loss", "target", "risk_reward", "timeframe", "strategy_type", "risks", "tags",
]
_STRATEGIES = {"momentum", "mean_reversion", "breakout", "value"}
_HORIZONS = {"low", "medium", "high"}


class _ReportSchema(BaseModel):
    """Structured-output schema for providers that support it (Gemini)."""
    conviction: int
    thesis: str
    reasons: list[str]
    horizon: str
    fundamental_summary: str
    technical_summary: str
    forecast_summary: str
    entry_zone: str
    stop_loss: str
    target: str
    risk_reward: str
    timeframe: str
    strategy_type: str
    risks: list[str]
    tags: list[str]


class ReportGenerator:
    def __init__(self):
        self.cfg = get_config()
        self.provider = self.cfg.llm_provider
        self._client = None  # lazily initialised per provider

    # ── public API ────────────────────────────────────────────────────────
    def generate(
        self, symbol: str, profile: dict, financials: dict, ratios: dict,
        analyst_estimates: dict, insider_trading: dict, indicators: dict,
        news: list, forecast: dict, fund_score: float, tech_score: float,
        direction: str = "long",
    ) -> dict:
        derived = self._derive_levels(indicators, forecast)
        name = _name_of(profile, symbol)

        payload = {
            "symbol": symbol,
            "name": name,
            "trade_direction": direction,
            "scores": {"fundamental": fund_score, "technical": tech_score},
            "profile": _trim(profile),
            "financials": _trim(financials),
            "ratios": _trim(ratios),
            "analyst_estimates": _trim(analyst_estimates),
            "insider_trading": _trim(insider_trading),
            "indicators": indicators,
            "kronos_forecast": {
                k: forecast.get(k) for k in (
                    "current_close", "forecast_close", "forecast_high",
                    "forecast_low", "expected_return_pct", "path_spread_pct",
                    "prob_up", "ret_q05_pct", "ret_q50_pct", "ret_q95_pct",
                    "terminal_vol_pct", "step_vol_pct", "n_paths",
                )
            } if forecast else {},
            "derived_levels": derived,
            "news": [_news_line(n) for n in (news or [])[:5]],
        }

        if self.provider == "none":
            return self._template_report(symbol, name, payload, derived,
                                         fund_score, tech_score)

        side_note = (
            "This is a SHORT idea: the forecast is bearish. Frame the thesis as a "
            "short/sell case, treat entry/stop/target as a short (stop ABOVE entry, "
            "target BELOW), and discuss downside catalysts. Do NOT write a bullish "
            "'buy' thesis.\n\n" if direction == "short" else
            "This is a LONG idea: frame it as a buy/accumulate case.\n\n")
        user_prompt = (
            "Produce the JSON research report for this security.\n\n"
            + side_note
            + json.dumps(payload, default=str, indent=2)
            + "\n\nRequired JSON keys: " + ", ".join(_REQUIRED_KEYS)
            + "\nconviction is an integer 1-5. strategy_type is one of: "
            + ", ".join(sorted(_STRATEGIES))
            + ". risks and tags are arrays of strings."
        )

        try:
            raw = self._call_llm(SYSTEM_PROMPT, user_prompt)
            report = self._parse(raw)
            return self._validate(report, symbol, name, derived, fund_score, tech_score)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s: LLM synthesis failed (%s) — using template", symbol, exc)
            return self._template_report(symbol, name, payload, derived,
                                         fund_score, tech_score)

    # ── provider dispatch (with retry/backoff) ────────────────────────────
    def _call_llm(self, system: str, user: str, schema=_ReportSchema) -> str:
        import time
        last_exc = None
        for attempt in range(3):
            try:
                if self.provider == "gemini":
                    return self._call_gemini(system, user, schema)
                if self.provider == "anthropic":
                    return self._call_anthropic(system, user)
                raise RuntimeError(f"unknown provider {self.provider}")
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                msg = str(exc).lower()
                transient = any(s in msg for s in (
                    "429", "rate", "resource exhausted", "quota",
                    "overloaded", "503", "unavailable", "timeout"))
                if transient and attempt < 2:
                    wait = 2 ** attempt * 2  # 2s, 4s
                    logger.info("LLM transient error, retrying in %ds: %s", wait, exc)
                    time.sleep(wait)
                    continue
                raise
        raise last_exc  # pragma: no cover

    def _call_gemini(self, system: str, user: str, schema=_ReportSchema) -> str:
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self.cfg.gemini_api_key)
        from google.genai import types
        cfg_kw = dict(system_instruction=system, response_mime_type="application/json",
                      temperature=0.4)
        if schema is not None:
            cfg_kw["response_schema"] = schema   # guarantees the report shape
        resp = self._client.models.generate_content(
            model=self.cfg.gemini_model, contents=user,
            config=types.GenerateContentConfig(**cfg_kw))
        return resp.text or ""

    # ── Layer-2 critic: audit computed numbers for financial coherence ────────
    def critique(self, packet: dict) -> dict | None:
        """LLM audit of a COMPUTED pick (not a re-analysis). Returns
        {coherent, severity, concerns} or None when no LLM provider is active."""
        if self.provider not in ("gemini", "anthropic"):
            return None
        user = ("Audit this automated pick for internal coherence. Return ONLY JSON "
                '{"coherent": bool, "severity": "low|medium|high", "concerns": [str]}.'
                "\n\n" + json.dumps(packet, default=str, indent=2))
        try:
            raw = self._call_llm(CRITIC_SYSTEM, user, schema=None)
            data = self._parse(raw)
            return {
                "coherent": bool(data.get("coherent", True)),
                "severity": str(data.get("severity", "low")).lower(),
                "concerns": [str(c) for c in (data.get("concerns") or []) if c][:6],
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug("critique failed: %s", exc)
            return None

    def _call_anthropic(self, system: str, user: str) -> str:
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.cfg.anthropic_api_key)
        msg = self._client.messages.create(
            model=self.cfg.resolved_anthropic_model,
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")

    # ── parsing + validation ──────────────────────────────────────────────
    @staticmethod
    def _parse(raw: str) -> dict:
        raw = raw.strip()
        # Strip accidental ```json fences.
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.DOTALL)
        if fence:
            raw = fence.group(1)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                return json.loads(m.group(0))
            raise

    def _validate(self, report: dict, symbol: str, name: str, derived: dict,
                  fund_score: float, tech_score: float) -> dict:
        report = dict(report) if isinstance(report, dict) else {}
        report["symbol"] = symbol
        report["name"] = report.get("name") or name

        conv = report.get("conviction", 3)
        try:
            conv = int(round(float(conv)))
        except (TypeError, ValueError):
            conv = 3
        report["conviction"] = max(1, min(5, conv))

        strat = str(report.get("strategy_type", "")).lower().replace(" ", "_")
        report["strategy_type"] = strat if strat in _STRATEGIES else _infer_strategy(derived)

        horizon = str(report.get("horizon", "")).lower().strip()
        report["horizon"] = horizon if horizon in _HORIZONS else _classify_horizon(
            report["strategy_type"], fund_score, tech_score, derived)
        report["reasons"] = _as_str_list(report.get("reasons")) or ["See thesis."]

        for key in ("thesis", "fundamental_summary", "technical_summary",
                    "forecast_summary", "entry_zone", "stop_loss", "target",
                    "risk_reward", "timeframe"):
            if not report.get(key):
                report[key] = derived.get(key, "n/a")

        report["risks"] = _as_str_list(report.get("risks")) or ["Data limited; verify independently."]
        report["tags"] = _as_str_list(report.get("tags"))
        report.setdefault("_scores", {"fundamental": fund_score, "technical": tech_score})
        return report

    # ── deterministic fallback ────────────────────────────────────────────
    def _template_report(self, symbol: str, name: str, payload: dict,
                         derived: dict, fund_score: float, tech_score: float) -> dict:
        fc = payload.get("kronos_forecast", {})
        exp = fc.get("expected_return_pct")
        prob_up = fc.get("prob_up")
        ind = payload.get("indicators", {})
        financials = payload.get("financials", {})
        ratios = payload.get("ratios", {})
        estimates = payload.get("analyst_estimates", {})
        insider = payload.get("insider_trading", {})
        conviction = _template_conviction(fund_score, tech_score, exp, prob_up)
        direction = "higher" if (exp or 0) > 0 else "lower"

        if exp is not None:
            prob_s = (f" P(up)={prob_up:.0%} across {fc.get('n_paths', '?')} paths;"
                      if isinstance(prob_up, (int, float)) else "")
            band = ""
            if fc.get("ret_q05_pct") is not None and fc.get("ret_q95_pct") is not None:
                band = (f" 90% range {fc['ret_q05_pct']:+.1f}% to "
                        f"{fc['ret_q95_pct']:+.1f}%.")
            forecast_summary = (
                f"Kronos projects {symbol} {direction} by {exp:+.1f}% (median "
                f"{fc.get('ret_q50_pct', exp):+.1f}%).{prob_s}{band}"
            )
        else:
            forecast_summary = "No Kronos forecast available for this name."

        strategy = _infer_strategy(derived)
        horizon = _classify_horizon(strategy, fund_score, tech_score, derived)
        reasons = _template_reasons(symbol, ind, fc, fund_score, tech_score)

        def m(k, suffix="%"):
            v = ind.get(k)
            return f"{v:+.1f}{suffix}" if isinstance(v, (int, float)) else "n/a"

        thesis = (
            f"{name} clears the screen with {fund_score:.0f}/100 on fundamentals "
            f"and {tech_score:.0f}/100 on technicals, and Kronos is the deciding "
            f"input: a {exp:+.1f}% central projection "
            f"({'bullish' if (exp or 0) > 0 else 'bearish'}) over the forecast window"
            f"{(', with P(up) ' + format(prob_up, '.0%')) if isinstance(prob_up,(int,float)) else ''}. "
            if exp is not None else f"{name} clears the screen ({fund_score:.0f}/100 "
            f"fundamental, {tech_score:.0f}/100 technical), but Kronos returned no "
            f"forecast so conviction is capped. "
        ) + (
            f"Trailing performance frames the setup: {m('ret_1m')} over 1 month, "
            f"{m('ret_3m')} over 3 months and {m('ret_1y')} over the past year, with "
            f"annualised volatility around {ind.get('ann_vol_pct','n/a')}%. Price sits "
            f"{m('pct_from_52w_hi')} from its 52-week high and {m('pct_from_52w_lo')} "
            f"above the low, {m('dist_sma50_pct')} versus its 50-day average. "
        ) + (
            f"This reads as a {horizon}-horizon, {strategy.replace('_',' ')} idea. "
            "This is a template summary (no LLM provider configured) - the numbers "
            "are real; the narrative is mechanical."
        )
        return {
            "symbol": symbol,
            "name": name,
            "conviction": conviction,
            "horizon": horizon,
            "reasons": reasons,
            "thesis": thesis,
            "fundamental_summary": _template_fundamental_summary(
                fund_score, financials, ratios, estimates, insider, ind),
            "technical_summary": (
                f"Technical screen {tech_score:.0f}/100. RSI(14) "
                f"{_fmt(ind.get('rsi14'))}, price {_fmt(ind.get('price'))}, "
                f"{m('dist_sma50_pct')} vs SMA50 and {m('dist_sma200_pct')} vs SMA200. "
                f"MACD histogram {_fmt(ind.get('macd_hist'))}, ATR(14) {_fmt(ind.get('atr14'))}, "
                f"Bollinger mid {_fmt(ind.get('bb_mid'))}, lower {_fmt(ind.get('bb_lower'))}, "
                f"upper {_fmt(ind.get('bb_upper'))}."
            ),
            "forecast_summary": forecast_summary,
            "entry_zone": derived["entry_zone"],
            "stop_loss": derived["stop_loss"],
            "target": derived["target"],
            "risk_reward": derived["risk_reward"],
            "timeframe": derived["timeframe"],
            "strategy_type": strategy,
            "risks": [
                f"Annualised volatility ~{ind.get('ann_vol_pct','n/a')}% - size accordingly.",
                f"Max 1y drawdown {ind.get('max_drawdown_1y_pct','n/a')}% shows downside history.",
                "Template synthesis; verify the fundamentals independently.",
            ],
            "tags": ["screened", "template", horizon + "_horizon"],
            "_scores": {"fundamental": fund_score, "technical": tech_score},
        }

    # ── number crunching ──────────────────────────────────────────────────
    @staticmethod
    def _derive_levels(indicators: dict, forecast: dict) -> dict:
        import math
        price = (indicators or {}).get("price")
        if price is None and forecast:
            price = forecast.get("current_close")
        atr = (indicators or {}).get("atr14")
        fc_high = (forecast or {}).get("forecast_high")
        fc_low = (forecast or {}).get("forecast_low")
        exp = (forecast or {}).get("expected_return_pct")
        prob_up = (forecast or {}).get("prob_up")
        step_vol = (forecast or {}).get("step_vol_pct")   # per-step (daily) %
        n_steps = len((forecast or {}).get("forecast_candles") or []) or 20
        timeframe = _timeframe_for_steps(n_steps)

        out = {
            "entry_zone": "n/a", "stop_loss": "n/a", "target": "n/a",
            "risk_reward": "n/a", "timeframe": timeframe,
        }
        if price is None:
            return out

        # Risk unit: prefer Kronos forward volatility (forward-looking), else ATR.
        if isinstance(step_vol, (int, float)) and step_vol > 0:
            # daily sigma scaled to the forecast horizon
            horizon_sigma = price * (step_vol / 100.0) * math.sqrt(max(n_steps, 1))
            risk_unit = max(horizon_sigma, price * 0.005)
            stop_basis = "vol-based (Kronos)"
        elif isinstance(atr, (int, float)) and atr > 0:
            risk_unit = atr
            stop_basis = "ATR-based"
        else:
            risk_unit = price * 0.02
            stop_basis = "estimated"

        entry_lo, entry_hi = price - 0.3 * risk_unit, price + 0.3 * risk_unit
        stop = (fc_low if (isinstance(fc_low, (int, float)) and fc_low < price)
                else price - 1.5 * risk_unit)
        target = (fc_high if (isinstance(fc_high, (int, float)) and fc_high > price)
                  else price + 2.0 * risk_unit)

        risk = max(price - stop, 1e-9)
        reward = max(target - price, 0.0)
        rr = reward / risk if risk > 0 else 0.0

        out.update({
            "entry_zone": f"${entry_lo:,.2f}-${entry_hi:,.2f}",
            "stop_loss": f"${stop:,.2f} ({stop_basis})",
            "target": f"${target:,.2f} (forecast high)" if fc_high else f"${target:,.2f}",
            "risk_reward": f"1:{rr:.1f}" if rr > 0 else "n/a",
            "timeframe": timeframe,
            "_price": price, "_atr": risk_unit, "_stop": stop, "_target": target,
            "_expected_return": exp, "_prob_up": prob_up,
        })
        return out


# ── module helpers ─────────────────────────────────────────────────────────
def _name_of(profile: dict, symbol: str) -> str:
    for k in ("companyName", "name", "longName", "shortName", "title"):
        v = (profile or {}).get(k)
        if isinstance(v, str) and v.strip():
            return v
    return symbol


def _fmt(v):
    if isinstance(v, (int, float)):
        return f"{v:.2f}"
    return "n/a"


def _fmt_pct_like(v):
    if not isinstance(v, (int, float)):
        return "n/a"
    # Some providers return 0.12, others 12.0 for 12%.
    pct = v * 100 if abs(v) <= 2 else v
    return f"{pct:+.1f}%"


def _fmt_money_like(v):
    if not isinstance(v, (int, float)):
        return "n/a"
    av = abs(v)
    if av >= 1_000_000_000:
        return f"{v / 1_000_000_000:.1f}B"
    if av >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    return f"{v:.0f}"


def _first_num(d: dict, *keys):
    if not isinstance(d, dict):
        return None
    for key in keys:
        value = d.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _first_text(d: dict, *keys):
    if not isinstance(d, dict):
        return None
    for key in keys:
        value = d.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _template_reasons(symbol, ind: dict, fc: dict, fund: float, tech: float) -> list[str]:
    """Concrete, number-citing reasons from the available metrics."""
    r = []
    exp = fc.get("expected_return_pct")
    prob = fc.get("prob_up")
    if isinstance(exp, (int, float)):
        s = f"Kronos central forecast {exp:+.1f}%"
        if isinstance(prob, (int, float)):
            s += f" with P(up) {prob:.0%}"
        if fc.get("ret_q05_pct") is not None:
            s += f" (90% range {fc['ret_q05_pct']:+.1f}% to {fc['ret_q95_pct']:+.1f}%)"
        r.append(s + ".")
    for label, key, unit in (
        ("1-month return", "ret_1m", "%"), ("3-month return", "ret_3m", "%"),
        ("1-year return", "ret_1y", "%")):
        v = ind.get(key)
        if isinstance(v, (int, float)):
            r.append(f"{label} {v:+.1f}{unit}.")
    if isinstance(ind.get("pct_from_52w_hi"), (int, float)):
        r.append(f"{ind['pct_from_52w_hi']:+.1f}% from the 52-week high.")
    if isinstance(ind.get("rsi14"), (int, float)):
        r.append(f"RSI(14) at {ind['rsi14']:.0f}.")
    if isinstance(ind.get("ann_vol_pct"), (int, float)):
        r.append(f"Annualised volatility {ind['ann_vol_pct']:.0f}%.")
    r.append(f"Screen scores: fundamental {fund:.0f}/100, technical {tech:.0f}/100.")
    return r[:6]


def _template_fundamental_summary(
    fund_score: float, financials: dict, ratios: dict, estimates: dict,
    insider: dict, ind: dict
) -> str:
    rev = _first_num(financials, "revenueGrowth", "revenue_growth_yoy", "revenueGrowthYoY", "revenueGrowthTTM")
    ni = _first_num(financials, "netIncome", "net_income", "netIncomeTTM")
    pe = _first_num(ratios, "peRatio", "pe", "priceEarningsRatio", "peRatioTTM")
    de = _first_num(ratios, "debtToEquity", "debt_to_equity", "debtEquityRatio")
    rating = _first_text(estimates, "consensus", "rating", "recommendation", "consensusRating")
    surprise = _first_num(estimates, "epsSurprise", "earningsSurprise", "lastSurprisePct")
    insider_net = _first_num(insider, "netShares", "net_buying", "netBuying", "netTransactionShares")

    parts = [f"Fundamental screen {fund_score:.0f}/100."]
    parts.append(f"Revenue growth {_fmt_pct_like(rev)}.")
    parts.append(f"Net income {_fmt_money_like(ni)}.")
    parts.append(f"P/E {_fmt(pe)}, debt/equity {_fmt(de)}.")
    if rating:
        parts.append(f"Analyst stance: {rating}.")
    if surprise is not None:
        parts.append(f"Last earnings surprise {_fmt_pct_like(surprise)}.")
    if insider_net is not None:
        parts.append(f"Insider net shares {_fmt(insider_net)}.")
    parts.append(
        f"Market context: 1y return {_fmt_pct_like(ind.get('ret_1y'))}, "
        f"max 1y drawdown {_fmt_pct_like(ind.get('max_drawdown_1y_pct'))}."
    )
    return " ".join(parts)


def _classify_horizon(strategy: str, fund: float, tech: float, derived: dict) -> str:
    """low = day-trade-like (fast/technical/volatile); high = long-term/fundamental."""
    price = derived.get("_price") or 0
    atr = derived.get("_atr") or 0
    vol_pct = (atr / price * 100) if price else 0
    fund = fund or 0
    tech = tech or 0
    if strategy in ("momentum", "breakout") and vol_pct >= 2.5:
        return "low"
    if strategy == "value" or fund >= 70:
        return "high"
    if vol_pct >= 3.0:
        return "low"
    if fund >= tech + 15:
        return "high"
    return "medium"


def _infer_strategy(derived: dict) -> str:
    exp = derived.get("_expected_return")
    if exp is not None and exp > 8:
        return "breakout"
    if exp is not None and exp > 0:
        return "momentum"
    if exp is not None and exp <= 0:
        return "mean_reversion"
    return "value"


def _timeframe_for_steps(n_steps: int) -> str:
    if n_steps >= 50:
        return "8-12 weeks"
    if n_steps >= 30:
        return "4-8 weeks"
    return "2-4 weeks"


def _template_conviction(fund: float, tech: float, exp, prob_up=None) -> int:
    base = (fund + tech) / 40.0  # 0-5 scale from 0-200 combined
    if exp is not None:
        base += 0.5 if exp > 5 else (-0.5 if exp < 0 else 0)
    if isinstance(prob_up, (int, float)):
        base += 0.5 if prob_up > 0.6 else (-0.5 if prob_up < 0.4 else 0)
    return max(1, min(5, int(round(base))))


def _as_str_list(v) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    return []


def _trim(d: dict, max_keys: int = 25) -> dict:
    """Keep payloads to the LLM compact."""
    if not isinstance(d, dict):
        return {}
    out = {}
    for i, (k, v) in enumerate(d.items()):
        if i >= max_keys:
            break
        if isinstance(v, (dict, list)) and len(str(v)) > 600:
            continue
        out[k] = v
    return out


def _news_line(n) -> str:
    if isinstance(n, dict):
        title = n.get("title") or n.get("headline") or ""
        date = n.get("date") or n.get("publishedAt") or ""
        return f"{date} {title}".strip()
    return str(n)
