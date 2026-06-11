"""RunPod serverless handler — Kronos GPU forecasting, scale-to-zero.

The endpoint wakes on a request, loads the model once per warm worker, answers
`forecast_batch`, and scales back to zero when idle ($0). The box (or Mac) calls
it via scanner.kronos_client when KRONOS_SERVERLESS_ENDPOINT + RUNPOD_API_KEY
are set — no pod to start, nothing to terminate.

Input  (event["input"]): {"items": [{"symbol","ohlcv"}], "pred_len": int, "n_paths": int}
Output (return value):    list of forecast dicts (same as KronosForecaster.forecast_batch)
"""
import os

os.environ.setdefault("KRONOS_REPO_PATH", "/Kronos")
os.environ.setdefault("KRONOS_MODEL", "NeoQuasar/Kronos-base")
os.environ.setdefault("KRONOS_TOKENIZER", "NeoQuasar/Kronos-Tokenizer-base")
os.environ.setdefault("KRONOS_DEVICE", "cuda")
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")

import runpod  # noqa: E402

_forecaster = None


def _get_forecaster():
    """Load Kronos once per worker; reused across requests while warm."""
    global _forecaster
    if _forecaster is None:
        from kronos_service.predictor import KronosForecaster
        _forecaster = KronosForecaster()
    return _forecaster


def handler(event):
    inp = (event or {}).get("input") or {}
    items = inp.get("items") or []
    if not items:
        return []
    pred_len = int(inp.get("pred_len") or 30)
    n_paths = int(inp.get("n_paths") or 12)
    return _get_forecaster().forecast_batch(items, pred_len=pred_len, n_paths=n_paths)


runpod.serverless.start({"handler": handler})
