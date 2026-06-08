"""Meta-model — the learned 'direction oracle'.

A single forecaster is a coin flip (the backtest proved it). This combines many
weak signals — Kronos return, fundamental + technical scores, momentum/vol
features — into one calibrated P(up), trained on the paper-trading ledger
(`scanner.paper`). Pure-numpy logistic regression (standardized features), so no
new dependency. It abstains until it has enough matured trades to be meaningful.

    python -m scanner.meta_model train     # fit on closed paper trades
    python -m scanner.meta_model info       # show weights + CV accuracy

Train regularly as the ledger grows; predictions improve as you paper-trade.
This is the engine you refine — not a magic call.
"""

from __future__ import annotations

import json
import logging
import math
from functools import lru_cache

import numpy as np

from scanner.config import get_config

logger = logging.getLogger("scanner.meta_model")

# Feature order is fixed and stored with the model.
FEATURES = [
    "predicted_return_pct", "prob_up", "fund_score", "tech_score", "conviction",
    "ret_1m", "ret_3m", "ret_1y", "ann_vol_pct", "rsi14", "macd_hist",
    "dist_sma50_pct", "dist_sma200_pct", "pct_from_52w_hi", "max_drawdown_1y_pct",
]
MIN_SAMPLES = 40


def _model_path():
    return get_config().project_root / "outputs" / "meta_model.json"


def _vec(rec: dict) -> list[float] | None:
    """Build a feature vector from a paper-ledger record."""
    feats = rec.get("features") or {}
    row = []
    for k in FEATURES:
        v = rec.get(k) if k in rec else feats.get(k)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            v = 0.0
        try:
            row.append(float(v))
        except (TypeError, ValueError):
            row.append(0.0)
    return row


def _fit_logistic(X, y, l2=1.0, iters=400, lr=0.1):
    """Standardize + gradient-descent logistic regression (numpy only)."""
    mu = X.mean(axis=0); sd = X.std(axis=0); sd[sd == 0] = 1.0
    Xs = (X - mu) / sd
    n, d = Xs.shape
    w = np.zeros(d); b = 0.0
    for _ in range(iters):
        z = Xs @ w + b
        p = 1 / (1 + np.exp(-np.clip(z, -30, 30)))
        gw = Xs.T @ (p - y) / n + l2 * w / n
        gb = float((p - y).mean())
        w -= lr * gw; b -= lr * gb
    return w, b, mu, sd


def train() -> dict:
    from scanner.paper import _read
    rows = [r for r in _read() if r.get("status") == "closed"
            and r.get("direction_correct") is not None]
    if len(rows) < MIN_SAMPLES:
        msg = f"need >={MIN_SAMPLES} closed paper trades to train, have {len(rows)}"
        logger.info(msg)
        return {"trained": False, "reason": msg, "have": len(rows)}

    X = np.array([_vec(r) for r in rows], dtype=float)
    # Label = was the move actually up (what we want to predict), not "we were right".
    y = np.array([1.0 if (r.get("realized_return_pct") or 0) > 0 else 0.0 for r in rows])

    # 5-fold CV accuracy for an honest read.
    idx = np.arange(len(X)); accs = []
    for k in range(5):
        te = idx[k::5]; tr = np.setdiff1d(idx, te)
        if len(te) == 0 or len(tr) < 10:
            continue
        w, b, mu, sd = _fit_logistic(X[tr], y[tr])
        ph = 1 / (1 + np.exp(-np.clip(((X[te] - mu) / sd) @ w + b, -30, 30)))
        accs.append(float(((ph > 0.5) == (y[te] > 0.5)).mean()))
    cv_acc = round(float(np.mean(accs)), 3) if accs else None

    w, b, mu, sd = _fit_logistic(X, y)
    model = {
        "features": FEATURES, "w": w.tolist(), "b": float(b),
        "mu": mu.tolist(), "sd": sd.tolist(),
        "n": len(rows), "cv_accuracy": cv_acc,
        "base_rate": round(float(y.mean()), 3),
    }
    _model_path().write_text(json.dumps(model, indent=2))
    _load.cache_clear()
    logger.info("Meta-model trained on %d trades; CV acc=%s (base rate %s)",
                len(rows), cv_acc, model["base_rate"])
    return {"trained": True, **{k: model[k] for k in ("n", "cv_accuracy", "base_rate")}}


@lru_cache(maxsize=1)
def _load() -> dict | None:
    p = _model_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return None


def predict_proba(rec: dict) -> float | None:
    """Calibrated P(up) for a pick, or None if no model is trained yet."""
    m = _load()
    if not m:
        return None
    w = np.array(m["w"]); mu = np.array(m["mu"]); sd = np.array(m["sd"])
    x = np.array(_vec(rec), dtype=float)
    z = float(((x - mu) / sd) @ w + m["b"])
    return round(1 / (1 + math.exp(-max(-30, min(30, z)))), 4)


def main() -> None:
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "info"
    if cmd == "train":
        print(json.dumps(train(), indent=2))
    else:
        m = _load()
        if not m:
            print("No meta-model trained yet. Paper-trade, then run: python -m scanner.meta_model train")
            return
        print(json.dumps({k: m[k] for k in ("n", "cv_accuracy", "base_rate")}, indent=2))
        print("weights:")
        for f, wv in sorted(zip(m["features"], m["w"]), key=lambda t: -abs(t[1])):
            print(f"  {f:22} {wv:+.3f}")


if __name__ == "__main__":
    main()
