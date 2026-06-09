"""Watchlist assembly, persistence, and markdown rendering."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from scanner.config import get_config

logger = logging.getLogger("scanner.output")


class WatchlistOutput:
    def __init__(self):
        self.cfg = get_config()

    def build(self, entries: list[dict], directive: str,
              total_scanned: int, total_screened: int,
              macro: dict | None = None, positions: list[dict] | None = None,
              exits: list[dict] | None = None, benchmarks: list[dict] | None = None,
              max_per_sector: int = 3) -> dict:
        """`entries` items: {report, forecast, fund_score, tech_score, sector}."""
        from scanner import scoring, sizing, sanity
        held = {p.get("symbol") for p in (positions or [])}
        items = []
        for e in entries:
            report = e.get("report", {})
            forecast = e.get("forecast") or {}
            vigil_score, score_breakdown = scoring.composite(
                report, forecast, e.get("fund_score"), e.get("tech_score"))
            report["_score"] = vigil_score
            report["_score_breakdown"] = score_breakdown
            size = sizing.from_pick(
                report, forecast, equity=self.cfg.account_equity,
                kelly_fraction_used=self.cfg.sizing_kelly_fraction,
                target_vol=self.cfg.sizing_target_vol)
            if size.get("weight_pct") is not None:
                report["_sizing"] = size
            # Self-check: run financial-coherence invariants on the assembled pick.
            violations = sanity.audit(report, forecast)
            if violations:
                report["_sanity"] = violations
                errs = [v for v in violations if v.get("severity") == "error"]
                logger.warning("Sanity: %s has %d violation(s)%s: %s",
                               report.get("symbol"), len(violations),
                               " (ERRORS)" if errs else "",
                               "; ".join(v["check"] + ":" + v["detail"] for v in violations[:4]))
            items.append({
                "symbol": report.get("symbol"),
                "name": report.get("name"),
                "score": vigil_score,
                "score_breakdown": score_breakdown,
                "conviction": int(report.get("conviction", 3)),
                "horizon": report.get("horizon", "medium"),
                "metrics": _pick_metrics(e.get("indicators") or {}),
                "decision_shapers": _decision_shapers(
                    e.get("indicators") or {}, forecast, e.get("fund_score"), e.get("tech_score")),
                "strategy_type": report.get("strategy_type", "value"),
                "direction": report.get("direction", "long"),
                "expected_return_pct": forecast.get("expected_return_pct"),
                "prob_up": forecast.get("prob_up"),
                "ret_q05_pct": forecast.get("ret_q05_pct"),
                "ret_q50_pct": forecast.get("ret_q50_pct"),
                "ret_q95_pct": forecast.get("ret_q95_pct"),
                "terminal_vol_pct": forecast.get("terminal_vol_pct"),
                "risk_reward": report.get("risk_reward", "n/a"),
                "timeframe": report.get("timeframe", "n/a"),
                "tags": report.get("tags", []),
                "sector": e.get("sector", ""),
                "held": report.get("symbol") in held,
                "fund_score": e.get("fund_score"),
                "tech_score": e.get("tech_score"),
                "forecast_candles": forecast.get("forecast_candles", []),
                "cone": forecast.get("cone"),
                "current_close": forecast.get("current_close"),
                "report": report,
            })

        items.sort(key=_sort_key, reverse=True)
        items = _diversify(items, self.cfg.max_watchlist_size, max_per_sector)
        for i, item in enumerate(items, start=1):
            item["rank"] = i

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "directive": directive or "(broad sweep)",
            "total_scanned": total_scanned,
            "total_screened": total_screened,
            "provider": self.cfg.llm_provider,
            "macro": macro or {},
            "benchmarks": benchmarks or [],
            "exits": exits or [],
            "positions_count": len(positions or []),
            "watchlist": items,
        }

    def save(self, watchlist: dict, path: str | None = None) -> str:
        outputs_dir = self.cfg.project_root / "outputs"
        outputs_dir.mkdir(exist_ok=True)
        if path is None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = str(outputs_dir / f"watchlist_{stamp}.json")
        Path(path).write_text(json.dumps(watchlist, indent=2, default=str))
        # Maintain a stable 'latest' pointer for the UI.
        (outputs_dir / "latest.json").write_text(json.dumps(watchlist, indent=2, default=str))
        logger.info("Saved watchlist -> %s", path)
        return path

    def to_markdown(self, watchlist: dict) -> str:
        lines = [
            f"# Scanner Watchlist - {watchlist.get('directive')}",
            "",
            f"Generated: {watchlist.get('generated_at')}  ",
            f"Scanned {watchlist.get('total_scanned')} -> screened "
            f"{watchlist.get('total_screened')} -> {len(watchlist.get('watchlist', []))} picks  ",
            f"Synthesis provider: {watchlist.get('provider')}",
            "",
        ]
        fc_cfg = watchlist.get("forecast_config") or {}
        if fc_cfg:
            lines.extend([
                f"Forecast: {fc_cfg.get('pred_len')} daily candles, "
                f"{fc_cfg.get('mc_paths')} Monte-Carlo paths",
                "",
            ])
        macro = watchlist.get("macro") or {}
        if macro:
            lines.append("**Macro.** " + "  ".join(f"{k}={v}" for k, v in macro.items()))
            lines.append("")
        benchmarks = watchlist.get("benchmarks") or []
        if benchmarks:
            parts = []
            for b in benchmarks:
                er = b.get("expected_return_pct")
                er_s = f"{er:+.1f}%" if isinstance(er, (int, float)) else "n/a"
                parts.append(f"{b.get('symbol')} {er_s}")
            lines.append("**Benchmark ETFs.** " + "  ".join(parts))
            lines.append("")
        exits = watchlist.get("exits") or []
        if exits:
            lines.append("## Exit signals (held names with negative forecast)")
            for ex in exits:
                er = ex.get("expected_return_pct")
                er_s = f"{er:+.1f}%" if isinstance(er, (int, float)) else "n/a"
                lines.append(f"- **{ex.get('symbol')}** {er_s} (P(up) {ex.get('prob_up')})")
            lines.append("")
        for item in watchlist.get("watchlist", []):
            r = item["report"]
            stars = "*" * item["conviction"] + "." * (5 - item["conviction"])
            exp = item.get("expected_return_pct")
            exp_s = f"{exp:+.1f}%" if isinstance(exp, (int, float)) else "n/a"
            lines += [
                f"## #{item['rank']}  {item['symbol']} - {item.get('name', '')}",
                f"**{stars}**  |  {item['strategy_type']}  |  Kronos {exp_s}  "
                f"|  R/R {item.get('risk_reward', 'n/a')}  |  {item.get('timeframe', '')}",
                "",
                f"**Thesis.** {r.get('thesis', '')}",
                "",
                f"- **Fundamentals.** {r.get('fundamental_summary', '')}",
                f"- **Technicals.** {r.get('technical_summary', '')}",
                f"- **Forecast.** {r.get('forecast_summary', '')}",
                "",
                f"**Strategy.** Entry {r.get('entry_zone', 'n/a')}  |  "
                f"Stop {r.get('stop_loss', 'n/a')}  |  Target {r.get('target', 'n/a')}",
                "",
                "**Risks.**",
                *[f"- {risk}" for risk in r.get("risks", [])],
                "",
                "---",
                "",
            ]
        return "\n".join(lines)


_METRIC_KEYS = [
    "ret_1m", "ret_3m", "ret_6m", "ret_1y", "ann_vol_pct", "pct_from_52w_hi",
    "pct_from_52w_lo", "max_drawdown_1y_pct", "dist_sma50_pct", "dist_sma200_pct",
    "rsi14", "macd_hist",
]


def _pick_metrics(ind: dict) -> dict:
    return {k: ind.get(k) for k in _METRIC_KEYS if ind.get(k) is not None}


def _decision_shapers(ind: dict, forecast: dict, fund_score, tech_score) -> dict:
    return {
        "scores": {"fundamental": fund_score, "technical": tech_score},
        "forecast": {
            "expected_return_pct": forecast.get("expected_return_pct"),
            "prob_up": forecast.get("prob_up"),
            "ret_q05_pct": forecast.get("ret_q05_pct"),
            "ret_q95_pct": forecast.get("ret_q95_pct"),
            "terminal_vol_pct": forecast.get("terminal_vol_pct"),
        },
        "technical": {
            "price": ind.get("price"),
            "rsi14": ind.get("rsi14"),
            "macd_hist": ind.get("macd_hist"),
            "atr14": ind.get("atr14"),
            "dist_sma50_pct": ind.get("dist_sma50_pct"),
            "dist_sma200_pct": ind.get("dist_sma200_pct"),
            "pct_from_52w_hi": ind.get("pct_from_52w_hi"),
            "max_drawdown_1y_pct": ind.get("max_drawdown_1y_pct"),
        },
    }


def _sort_key(item: dict):
    """Rank by the composite Vigil score first (it already folds in conviction,
    barrier edge, calibrated P(up) and quality), then conviction and raw return
    as tie-breakers."""
    score = item.get("score")
    score = score if isinstance(score, (int, float)) else -1
    exp = item.get("expected_return_pct")
    exp = exp if isinstance(exp, (int, float)) else -999
    return (score, item.get("conviction", 0), exp)


def _diversify(items: list[dict], max_size: int, max_per_sector: int) -> list[dict]:
    """Greedy sector cap: avoid a watchlist of N correlated names. Falls back
    to filling remaining slots if the cap leaves the list short."""
    chosen, counts, overflow = [], {}, []
    for it in items:
        sec = (it.get("sector") or "").lower() or "_none"
        if counts.get(sec, 0) < max_per_sector:
            chosen.append(it)
            counts[sec] = counts.get(sec, 0) + 1
        else:
            overflow.append(it)
        if len(chosen) >= max_size:
            return chosen[:max_size]
    for it in overflow:  # relax the cap only if we'd otherwise be short
        if len(chosen) >= max_size:
            break
        chosen.append(it)
    return chosen[:max_size]
