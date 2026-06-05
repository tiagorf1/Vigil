"""Forecast calibration — does Kronos actually call direction on your universe?

Walks past `outputs/watchlist_*.json`, and for every pick whose forecast window
has elapsed, fetches the realized price from OpenAlice and compares it to what
Kronos predicted. Writes `outputs/calibration.json` (read by the UI).

Metrics:
  hit_rate     — share of picks where forecast direction matched realized
  mae_ret_pct  — mean absolute error of expected vs realized return
  brier        — mean (prob_up - realized_up)^2, lower is better (0.25 = coin flip)

Run:  python -m scanner.calibrate
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from scanner.config import get_config
from scanner.openalice_client import OpenAliceClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("scanner.calibrate")


def _load_history(outputs_dir: Path) -> list[dict]:
    picks = []
    for f in sorted(outputs_dir.glob("watchlist_*.json")):
        try:
            wl = json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            continue
        gen = wl.get("generated_at")
        for item in wl.get("watchlist", []):
            candles = item.get("forecast_candles") or []
            if not candles or not item.get("current_close"):
                continue
            end_ts = candles[-1].get("ts")
            picks.append({
                "symbol": item["symbol"],
                "generated_at": gen,
                "entry": item["current_close"],
                "expected_return_pct": item.get("expected_return_pct"),
                "prob_up": item.get("prob_up"),
                "horizon_end": end_ts,
            })
    return picks


def _matured(pick: dict) -> bool:
    try:
        end = datetime.fromisoformat(str(pick["horizon_end"])[:19])
    except (ValueError, TypeError):
        return False
    return datetime.now() >= end


async def calibrate() -> dict:
    cfg = get_config()
    outputs_dir = cfg.project_root / "outputs"
    picks = _load_history(outputs_dir)
    matured = [p for p in picks if _matured(p)]
    logger.info("History: %d picks, %d matured", len(picks), len(matured))

    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "n_total": len(picks), "n_matured": 0,
        "hit_rate": None, "mae_ret_pct": None, "brier": None, "samples": [],
    }
    if not matured:
        result["note"] = "No forecasts have matured yet. Re-run after the horizon elapses."
        (outputs_dir / "calibration.json").write_text(json.dumps(result, indent=2))
        return result

    hits = errs = brier = scored = 0.0
    samples = []
    async with OpenAliceClient(cfg.openalice_mcp_url) as oa:
        for p in matured:
            realized = await _realized_return(oa, p)
            if realized is None:
                continue
            scored += 1
            exp = p.get("expected_return_pct") or 0.0
            hit = (realized > 0) == (exp > 0)
            hits += 1 if hit else 0
            errs += abs(exp - realized * 100)  # realized is fraction
            if isinstance(p.get("prob_up"), (int, float)):
                brier += (p["prob_up"] - (1 if realized > 0 else 0)) ** 2
            samples.append({
                "symbol": p["symbol"], "generated_at": p["generated_at"],
                "expected_return_pct": exp, "realized_return_pct": round(realized * 100, 2),
                "direction_correct": hit,
            })

    if scored:
        result.update({
            "n_matured": int(scored),
            "hit_rate": round(hits / scored, 3),
            "mae_ret_pct": round(errs / scored, 2),
            "brier": round(brier / scored, 3) if scored else None,
            "samples": samples[-50:],
        })
    (outputs_dir / "calibration.json").write_text(json.dumps(result, indent=2))
    logger.info("Calibration: hit_rate=%s mae=%s brier=%s (n=%d)",
                result["hit_rate"], result["mae_ret_pct"], result["brier"], int(scored))
    return result


async def _realized_return(oa: OpenAliceClient, pick: dict) -> float | None:
    """Realized fractional return from entry to the close nearest horizon_end."""
    ohlcv = await oa.get_ohlcv(pick["symbol"], interval="1d", bars=450)
    if not ohlcv:
        return None
    try:
        end = datetime.fromisoformat(str(pick["horizon_end"])[:19])
    except (ValueError, TypeError):
        return None
    best = None
    for row in ohlcv:
        ts = row.get("ts")
        close = row.get("close")
        if ts is None or close is None:
            continue
        try:
            d = datetime.fromisoformat(str(ts)[:19])
        except ValueError:
            continue
        if d <= end + timedelta(days=3):
            best = float(close)  # last close on/just after horizon
    if best is None or not pick.get("entry"):
        return None
    return best / pick["entry"] - 1.0


def main() -> None:
    res = asyncio.run(calibrate())
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
