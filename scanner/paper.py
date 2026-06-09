"""Paper-trading ledger — the feedback loop that lets Vigil actually improve.

Every scan logs its picks (with the features that drove them and the predicted
probability) to an append-only journal. Later, `score` matures the open entries
against realized prices and records the outcome. That growing labeled dataset is
what trains the meta-model (the real path to a "direction oracle") and what
honestly measures whether Vigil is getting better.

    python -m scanner.paper score     # mature + score open trades (run daily)
    python -m scanner.paper stats     # running hit-rate, avg return, equity
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scanner.config import get_config

logger = logging.getLogger("scanner.paper")

_FEATURE_KEYS = ("ret_1m", "ret_3m", "ret_1y", "ann_vol_pct", "rsi14",
                 "macd_hist", "dist_sma50_pct", "dist_sma200_pct",
                 "pct_from_52w_hi", "max_drawdown_1y_pct")


def _ledger_path() -> Path:
    d = get_config().project_root / "outputs"
    d.mkdir(exist_ok=True)
    return d / "paper_trades.jsonl"


def log_signals(watchlist: dict, horizon_days: int) -> int:
    """Append every watchlist pick as an OPEN paper trade. Cheap; call per scan."""
    path = _ledger_path()
    now = datetime.now(timezone.utc)
    n = 0
    with path.open("a") as fh:
        for it in watchlist.get("watchlist", []):
            entry = it.get("current_close")
            if not entry:
                continue
            item_horizon = int(it.get("horizon_days") or horizon_days)
            rec = {
                "id": f"{it['symbol']}|{now.strftime('%Y%m%dT%H%M%S')}",
                "opened_at": now.isoformat(timespec="seconds"),
                "due_at": (now + timedelta(days=int(item_horizon * 1.5))).isoformat(timespec="seconds"),
                "symbol": it["symbol"],
                "name": it.get("name"),
                "asset_class": _ac(it),
                "horizon_days": item_horizon,
                "entry": entry,
                "predicted_return_pct": it.get("expected_return_pct"),
                "prob_up": it.get("prob_up"),
                "conviction": it.get("conviction"),
                "fund_score": it.get("fund_score"),
                "tech_score": it.get("tech_score"),
                "strategy": it.get("strategy_type"),
                "calibrated": it.get("calibrated"),
                "calibration_n": it.get("calibration_n"),
                "calibration_generation": it.get("calibration_generation") or "legacy_unknown",
                "vigil_engine_version": 2,
                "features": {k: (it.get("metrics") or {}).get(k) for k in _FEATURE_KEYS},
                "status": "open",
            }
            fh.write(json.dumps(rec, default=str) + "\n")
            n += 1
    logger.info("Paper ledger: logged %d open signals", n)
    return n


def _ac(item: dict) -> str:
    if item.get("asset_class"):
        return str(item["asset_class"]).lower()
    s = (item.get("symbol") or "").upper()
    if s.endswith("=X"):
        return "forex"
    if s.endswith("=F"):
        return "commodity"
    if s.startswith("^"):
        return "index"
    if s.endswith(("USD", "USDT")):
        return "crypto"
    return "equity"


def _read() -> list[dict]:
    path = _ledger_path()
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _write(rows: list[dict]) -> None:
    _ledger_path().write_text("\n".join(json.dumps(r, default=str) for r in rows) + "\n")


async def score() -> dict:
    """Mature open trades whose horizon has elapsed; record realized outcome."""
    from scanner.market_data import fallback_ohlcv
    rows = _read()
    now = datetime.now(timezone.utc)
    matured = 0
    for r in rows:
        if r.get("status") != "open":
            continue
        try:
            due = datetime.fromisoformat(r["due_at"])
        except (ValueError, KeyError):
            continue
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        if now < due:
            continue
        ohlcv = await fallback_ohlcv(r["symbol"], bars=30)
        if not ohlcv:
            continue
        last = ohlcv[-1]["close"]
        realized = last / r["entry"] - 1.0
        pred = (r.get("predicted_return_pct") or 0.0) / 100.0
        r["status"] = "closed"
        r["closed_at"] = now.isoformat(timespec="seconds")
        r["realized_return_pct"] = round(realized * 100, 3)
        r["direction_correct"] = bool((pred > 0) == (realized > 0))
        matured += 1
    if matured:
        _write(rows)
    logger.info("Paper score: matured %d trades", matured)
    return stats()


def stats() -> dict:
    rows = _read()
    closed = [r for r in rows if r.get("status") == "closed"]
    scored_closed = _primary_rows(closed)
    out = {"total": len(rows), "open": sum(1 for r in rows if r.get("status") == "open"),
           "closed": len(closed), "closed_scored": len(scored_closed),
           "legacy_closed": len(closed) - len(scored_closed)}
    if closed and scored_closed is not closed:
        out["note"] = "Main stats prefer sample-backed calibration-era trades; legacy/default trades are counted separately."
    if scored_closed:
        hits = sum(1 for r in scored_closed if r.get("direction_correct"))
        rets = [r.get("realized_return_pct", 0) for r in scored_closed]
        out["hit_rate"] = round(hits / len(scored_closed), 3)
        out["avg_realized_pct"] = round(sum(rets) / len(rets), 2)
        # naive equity if you took every pick equal-weight
        eq = 1.0
        for x in rets:
            eq *= (1 + x / 100.0)
        out["cumulative_equity"] = round(eq, 4)
        # by conviction bucket — does higher conviction actually win more?
        by = {}
        for r in scored_closed:
            c = r.get("conviction") or 0
            by.setdefault(c, []).append(1 if r.get("direction_correct") else 0)
        out["hit_by_conviction"] = {str(k): round(sum(v) / len(v), 3) for k, v in sorted(by.items())}
    return out


def _primary_rows(closed: list[dict]) -> list[dict]:
    """Prefer the current, sample-backed calibration era for headline stats."""
    sample_backed = [r for r in closed if r.get("calibration_generation") == "sample_backed"]
    return sample_backed or closed


def main() -> None:
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "score":
        print(json.dumps(asyncio.run(score()), indent=2))
    else:
        print(json.dumps(stats(), indent=2))


if __name__ == "__main__":
    main()
