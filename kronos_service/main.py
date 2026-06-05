"""FastAPI wrapper around Kronos.

Loads the model once on startup and keeps it warm. The scanner's KronosClient
talks to this service over HTTP so the ~100MB model is never reloaded mid-scan.

Run standalone:
    uvicorn kronos_service.main:app --port 8765
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from scanner.config import get_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("kronos_service")

# Populated on startup. Module-level so the route handler can reach it.
_state: dict = {"forecaster": None}


class ForecastRequest(BaseModel):
    symbol: str
    ohlcv: list[dict] = Field(..., description="[{ts, open, high, low, close, volume}, ...]")
    pred_len: int = 20
    sample_count: int = 3
    n_paths: int | None = None


class ForecastBatchItem(BaseModel):
    symbol: str
    ohlcv: list[dict]


class ForecastBatchRequest(BaseModel):
    items: list[ForecastBatchItem]
    pred_len: int = 20
    n_paths: int | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Import here so a bad Kronos path fails loudly at startup, not import time.
    from kronos_service.predictor import KronosForecaster

    cfg = get_config()
    logger.info("Starting Kronos service on port %d", cfg.kronos_service_port)
    _state["forecaster"] = KronosForecaster()
    yield
    _state["forecaster"] = None


app = FastAPI(title="Kronos Forecast Service", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    forecaster = _state["forecaster"]
    cfg = get_config()
    return {
        "status": "ok" if forecaster is not None else "loading",
        "model": cfg.kronos_model,
        "device": getattr(forecaster, "device", None),
    }


@app.post("/forecast")
def forecast(req: ForecastRequest) -> dict:
    forecaster = _state["forecaster"]
    if forecaster is None:
        raise HTTPException(status_code=503, detail="model still loading")
    try:
        return forecaster.forecast(
            symbol=req.symbol,
            ohlcv=req.ohlcv,
            pred_len=req.pred_len,
            sample_count=req.sample_count,
            n_paths=req.n_paths,
        )
    except ValueError as exc:
        # Bad/insufficient input for this symbol — caller should skip it.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface as 500, keep service alive
        logger.exception("forecast failed for %s", req.symbol)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/forecast_batch")
def forecast_batch(req: ForecastBatchRequest) -> dict:
    forecaster = _state["forecaster"]
    if forecaster is None:
        raise HTTPException(status_code=503, detail="model still loading")
    try:
        results = forecaster.forecast_batch(
            items=[{"symbol": it.symbol, "ohlcv": it.ohlcv} for it in req.items],
            pred_len=req.pred_len,
            n_paths=req.n_paths,
        )
        return {"results": results}
    except Exception as exc:  # noqa: BLE001
        logger.exception("batch forecast failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
