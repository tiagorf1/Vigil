"""Remote scan worker.

Run this on a remote CPU/GPU box when local scans become too heavy:

    python -m scanner.worker

It exposes a tiny job API:
    POST /jobs
    GET  /jobs/{job_id}
    GET  /jobs/{job_id}/result

The worker runs the same scanner pipeline as the local app, but can be configured
with larger caps and a local/remote Kronos service on that machine.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from scanner.config import get_config

app = FastAPI(title="Vigil Remote Worker", version="0.1.0")

JOBS: dict[str, dict] = {}
LOCK = threading.Lock()


def _auth(token: str | None) -> None:
    """If VIGIL_WORKER_TOKEN is set, require it on every request (X-Vigil-Token).
    Lets you expose the port safely without handing the world free compute."""
    want = os.environ.get("VIGIL_WORKER_TOKEN", "").strip()
    if want and (token or "").strip() != want:
        raise HTTPException(status_code=401, detail="bad or missing X-Vigil-Token")


class JobRequest(BaseModel):
    directive: str = ""
    asset_class: str | None = None
    provider: str | None = None
    max_results: int | None = None
    pred_len: int | None = None
    mc_paths: int | None = None
    offline: bool = False
    notify: bool = False
    full_index: bool = False
    max_screened_size: int | None = None


@app.post("/jobs")
def create_job(req: JobRequest, x_vigil_token: str | None = Header(None)) -> dict:
    _auth(x_vigil_token)
    with LOCK:
        if any(j.get("status") in {"queued", "running"} for j in JOBS.values()):
            raise HTTPException(status_code=409, detail="Worker already has an active job.")
        job_id = uuid.uuid4().hex[:12]
        JOBS[job_id] = {
            "id": job_id,
            "status": "queued",
            "stage_text": "queued",
            "log": [],
            "error": None,
            "result_path": None,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "request": req.model_dump(),
        }
    threading.Thread(target=_run_job, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id, "status": "queued"}


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.get("/jobs/{job_id}/result")
def get_result(job_id: str, x_vigil_token: str | None = Header(None)) -> JSONResponse:
    _auth(x_vigil_token)
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.get("status") != "done" or not job.get("result_path"):
        raise HTTPException(status_code=409, detail="job is not complete")
    path = Path(job["result_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="result file missing")
    import json
    return JSONResponse(json.loads(path.read_text()))


def _run_job(job_id: str, req: JobRequest) -> None:
    import scanner.run as runmod

    def on_status(msg: str) -> None:
        job = JOBS[job_id]
        job["stage_text"] = msg
        job["log"].append(msg)
        job["log"] = job["log"][-100:]

    job = JOBS[job_id]
    job["status"] = "running"
    runmod.STATUS_CALLBACK = on_status

    old_env = {
        "LLM_PROVIDER": os.environ.get("LLM_PROVIDER"),
        "MAX_INDEX_COMPONENTS_LOCAL": os.environ.get("MAX_INDEX_COMPONENTS_LOCAL"),
        "MAX_SCREENED_SIZE": os.environ.get("MAX_SCREENED_SIZE"),
    }
    try:
        if req.provider:
            os.environ["LLM_PROVIDER"] = req.provider
        if req.full_index:
            os.environ["MAX_INDEX_COMPONENTS_LOCAL"] = "0"
        if req.max_screened_size is not None:
            os.environ["MAX_SCREENED_SIZE"] = str(req.max_screened_size)
        get_config.cache_clear()  # type: ignore[attr-defined]

        ns = argparse.Namespace(
            directive=req.directive,
            asset_class=req.asset_class,
            from_file=None,
            max_results=req.max_results,
            provider=req.provider,
            pred_len=req.pred_len,
            mc_paths=req.mc_paths,
            no_ui=True,
            push_inbox=False,
            stage_orders=False,
            notify=req.notify,
            no_notify=not req.notify,
            offline=req.offline,
        )
        asyncio.run(runmod.preflight(offline=req.offline))
        path = asyncio.run(runmod.run_scan(ns))
        job["result_path"] = path
        job["status"] = "done" if path else "error"
        if not path:
            job["error"] = "scan produced no output"
    except Exception as exc:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_config.cache_clear()  # type: ignore[attr-defined]
        runmod.STATUS_CALLBACK = None


def main() -> None:
    import uvicorn
    port = int(os.environ.get("VIGIL_WORKER_PORT", "8090"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
