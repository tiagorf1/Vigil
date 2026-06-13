"""Historical scorecards for live Vigil picks.

This module is intentionally boring: it reads the artifacts Vigil already
creates (`backtest.json`, `calibration.json`, and `paper_trades.jsonl`) and
turns them into a compact report card that can travel with every watchlist pick.
The goal is trust, not another model.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from scanner.config import get_config


def for_pick(symbol: str, asset_class: str | None, horizon_days: int | None) -> dict:
    """Return the model + Vigil paper-track record relevant to one pick."""
    ac = _normalize_asset_class(symbol, asset_class)
    horizon = int(horizon_days or 0)
    return {
        "asset_class": ac,
        "horizon_days": horizon or None,
        "model": _model_record(ac, horizon),
        "vigil": _vigil_record(ac, horizon),
        "calibration": _calibration_record(),
    }


def _outputs_dir() -> Path:
    return get_config().project_root / "outputs"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


@lru_cache(maxsize=1)
def _backtest() -> dict:
    return _read_json(_outputs_dir() / "backtest.json")


@lru_cache(maxsize=1)
def _calibration() -> dict:
    return _read_json(_outputs_dir() / "calibration.json")


@lru_cache(maxsize=1)
def _paper_rows() -> tuple[dict, ...]:
    path = _outputs_dir() / "paper_trades.jsonl"
    if not path.exists():
        return ()
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return tuple(rows)


def reload() -> None:
    """Clear cached file reads after a new backtest/calibration run."""
    _backtest.cache_clear()
    _calibration.cache_clear()
    _paper_rows.cache_clear()


def _model_record(asset_class: str, horizon: int) -> dict:
    bt = _backtest()
    scorecard = bt.get("scorecard") or {}
    key, row = _nearest_scorecard(scorecard, asset_class, horizon)
    if not row:
        overall = bt.get("overall") or {}
        return {
            "available": False,
            "note": "No factor scorecard yet. Run `python -m scanner.factor_backtest`.",
            "overall_n": overall.get("n"),
            "overall_direction_hit_rate": overall.get("hit_rate_debiased"),
            "overall_cone_coverage": overall.get("model_ci95_coverage"),
        }
    return {
        "available": True,
        "bucket": key,
        "n": row.get("n"),
        "direction_hit_rate": row.get("hit_rate_debiased") or row.get("hit_rate_raw"),
        "raw_direction_hit_rate": row.get("hit_rate_raw"),
        "cone_coverage": row.get("model_ci95_coverage"),
        "mae_pct": row.get("mae_pct"),
        "bias_pct": row.get("bias_pct"),
        "rank_corr": row.get("rank_corr"),
        "r2": row.get("r2"),
        "shrink_factor": row.get("shrink_factor"),
        "residual_sigma_pct": row.get("residual_sigma_pct"),
    }


def _nearest_scorecard(scorecard: dict, asset_class: str, horizon: int) -> tuple[str | None, dict | None]:
    parsed = []
    for key, row in scorecard.items():
        if "@" not in key:
            continue
        ac, h = key.rsplit("@", 1)
        try:
            parsed.append((ac, int(h), key, row))
        except ValueError:
            continue
    if not parsed:
        return None, None
    same = [x for x in parsed if x[0] == asset_class]
    pool = same or parsed
    if horizon > 0:
        ac, h, key, row = min(pool, key=lambda x: abs(x[1] - horizon))
    else:
        ac, h, key, row = max(pool, key=lambda x: (x[3].get("n") or 0))
    return key, row


def _vigil_record(asset_class: str, horizon: int) -> dict:
    closed = [r for r in _paper_rows() if r.get("status") == "closed"]
    current = [r for r in closed if r.get("calibration_generation") == "sample_backed"]
    pool = current or closed
    exact = _asset_horizon_rows(pool, asset_class, horizon)
    same_class = _asset_rows(pool, asset_class)
    rows = exact if len(exact) >= 5 else (same_class if len(same_class) >= 5 else pool)
    out = _summarize_paper(rows)
    out["bucket"] = (
        f"{asset_class}@~{horizon}" if rows is exact and horizon
        else asset_class if rows is same_class
        else "all"
    )
    out["sample_backed_closed"] = len(current)
    out["legacy_closed"] = len(closed) - len(current)
    out["generation"] = "sample_backed" if current else ("legacy_or_default" if closed else None)
    out["open"] = sum(1 for r in _paper_rows() if r.get("status") == "open")
    out["total"] = len(_paper_rows())
    if not closed:
        out["note"] = "No closed paper trades yet. Vigil will fill this in as past picks mature."
    elif not current:
        out["note"] = "Using legacy/default-calibration trades until sample-backed picks mature."
    elif rows is closed and same_class is not closed:
        out["note"] = "Using all closed paper trades until this asset bucket has enough samples."
    return out


def _asset_horizon_rows(rows: list[dict], asset_class: str, horizon: int) -> list[dict]:
    return [
        r for r in rows
        if _normalize_asset_class(r.get("symbol", ""), r.get("asset_class")) == asset_class
        and (not horizon or abs(int(r.get("horizon_days") or 0) - horizon) <= 5)
    ]


def _asset_rows(rows: list[dict], asset_class: str) -> list[dict]:
    return [
        r for r in rows
        if _normalize_asset_class(r.get("symbol", ""), r.get("asset_class")) == asset_class
    ]


def _summarize_paper(rows: list[dict]) -> dict:
    out = {"available": bool(rows), "closed": len(rows)}
    if not rows:
        return out
    hits = [1 if r.get("direction_correct") else 0 for r in rows]
    returns = [
        float(r.get("realized_return_pct"))
        for r in rows
        if isinstance(r.get("realized_return_pct"), (int, float))
    ]
    briers = []
    for r in rows:
        p = r.get("prob_up")
        hit = r.get("direction_correct")
        pred = r.get("predicted_return_pct")
        if isinstance(p, (int, float)) and isinstance(pred, (int, float)) and hit is not None:
            # Convert direction-correct back into realized-up for long/short agnostic
            # records. If predicted down and direction was correct, realized_up=False.
            predicted_up = pred > 0
            realized_up = predicted_up if hit else not predicted_up
            briers.append((p - (1 if realized_up else 0)) ** 2)
    out.update({
        "hit_rate": round(sum(hits) / len(hits), 3) if hits else None,
        "avg_realized_pct": round(sum(returns) / len(returns), 2) if returns else None,
        "brier": round(sum(briers) / len(briers), 3) if briers else None,
    })
    by_conviction: dict[str, list[int]] = {}
    for r, hit in zip(rows, hits):
        c = str(r.get("conviction") or "unknown")
        by_conviction.setdefault(c, []).append(hit)
    out["hit_by_conviction"] = {
        k: round(sum(v) / len(v), 3) for k, v in sorted(by_conviction.items())
    }
    return out


def _calibration_record() -> dict:
    cal = _calibration()
    if not cal:
        return {"available": False}
    return {
        "available": True,
        "n_matured": cal.get("n_matured"),
        "hit_rate": cal.get("hit_rate"),
        "mae_ret_pct": cal.get("mae_ret_pct"),
        "brier": cal.get("brier"),
        "generated_at": cal.get("generated_at"),
    }


def _normalize_asset_class(symbol: str, asset_class: str | None) -> str:
    ac = (asset_class or "").lower().strip()
    if ac:
        return ac
    up = (symbol or "").upper()
    if up.endswith("=X"):
        return "forex"
    if up.endswith("=F"):
        return "commodity"
    if up.startswith("^"):
        return "index"
    if up.endswith(("USD", "USDT")):
        return "crypto"
    if up in {"SPY", "QQQ", "DIA", "IWM", "GLD", "SLV", "USO"}:
        return "etf"
    return "equity"
