"""Scanner control-panel server.

A small FastAPI app so you can drive the scanner from the browser instead of the
terminal: configure a scan, hit RUN, watch live progress, and browse history.

Run:
    python -m scanner.server          # then open http://127.0.0.1:8080
or just double-click  Scanner.command
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from scanner.config import get_config
from scanner.openalice_client import OpenAliceClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("scanner.server")

CFG = get_config()
UI_DIR = CFG.project_root / "ui"
OUTPUTS_DIR = CFG.project_root / "outputs"

# Single in-memory job (one scan at a time).
JOB: dict = {
    "running": False, "kind": None, "stage": 0, "total": 6,
    "stage_text": "idle", "log": [], "result": None, "error": None,
    "started_at": None, "directive": None,
}

app = FastAPI(title="Scanner Control Panel", version="1.0.0")


class ScanRequest(BaseModel):
    directive: str = ""
    asset_class: str | None = None      # equity | crypto | index | etf | commodity | forex | None(auto)
    provider: str | None = None         # gemini | anthropic | none
    max_results: int | None = None
    pred_len: int | None = None         # forecast horizon in daily candles
    mc_paths: int | None = None         # Monte-Carlo Kronos paths
    push_inbox: bool = False
    stage_orders: bool = False
    notify: bool = False                # force a Telegram signal for this scan


# ── progress sink ──────────────────────────────────────────────────────────
def _on_status(msg: str) -> None:
    JOB["log"].append(msg)
    JOB["log"] = JOB["log"][-60:]
    JOB["stage_text"] = msg
    # Parse "[n/6] ..." stage markers.
    if msg.startswith("[") and "/" in msg[:6]:
        try:
            n = int(msg[1:msg.index("/")])
            JOB["stage"] = n
        except (ValueError, IndexError):
            pass


def _reset_job(kind: str, directive: str) -> None:
    JOB.update(running=True, kind=kind, stage=0, stage_text="starting...",
               log=[], result=None, error=None,
               started_at=datetime.now().isoformat(timespec="seconds"),
               directive=directive)


# ── background workers ─────────────────────────────────────────────────────
def _run_scan_job(req: ScanRequest) -> None:
    import scanner.run as runmod
    runmod.STATUS_CALLBACK = _on_status
    try:
        if req.provider:
            os.environ["LLM_PROVIDER"] = req.provider
            get_config.cache_clear()  # type: ignore[attr-defined]
        ns = argparse.Namespace(
            directive=req.directive or "", asset_class=req.asset_class,
            from_file=None, max_results=req.max_results, provider=req.provider,
            pred_len=req.pred_len, mc_paths=req.mc_paths,
            no_ui=True, push_inbox=req.push_inbox, stage_orders=req.stage_orders,
            notify=req.notify, no_notify=False, offline=False,
        )
        asyncio.run(runmod.preflight())
        path = asyncio.run(runmod.run_scan(ns))
        JOB["result"] = path
        if not path:
            JOB["error"] = JOB["error"] or "Scan produced no watchlist (see log)."
    except SystemExit as exc:
        JOB["error"] = str(exc).strip() or "Aborted."
    except Exception as exc:  # noqa: BLE001
        logger.exception("scan job failed")
        JOB["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        JOB["running"] = False
        JOB["stage"] = JOB["total"]
        runmod.STATUS_CALLBACK = None


def _run_calibrate_job() -> None:
    from scanner.calibrate import calibrate
    try:
        _on_status("Calibrating against past forecasts...")
        res = asyncio.run(calibrate())
        JOB["result"] = res
        _on_status(f"Calibration done: hit_rate={res.get('hit_rate')} "
                   f"(n={res.get('n_matured')})")
    except SystemExit as exc:
        JOB["error"] = str(exc).strip() or "Aborted."
    except Exception as exc:  # noqa: BLE001
        logger.exception("calibrate job failed")
        JOB["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        JOB["running"] = False
        JOB["stage"] = JOB["total"]


# ── API ────────────────────────────────────────────────────────────────────
@app.post("/api/scan")
def start_scan(req: ScanRequest) -> dict:
    if JOB["running"]:
        raise HTTPException(status_code=409, detail="A scan is already running.")
    _reset_job("scan", req.directive or "(broad sweep)")
    worker = get_config().vigil_worker_url
    target = _run_remote_job if worker else _run_scan_job
    threading.Thread(target=target, args=(req,), daemon=True).start()
    return {"started": True, "where": "cloud" if worker else "local"}


def _run_remote_job(req: ScanRequest) -> None:
    """Forward the scan to the cloud worker; mirror its progress; save the result
    locally so the cockpit renders it. This is the 'never on the Mac' path."""
    import time as _t
    cfg = get_config()
    base = cfg.vigil_worker_url.rstrip("/")
    hdr = {"X-Vigil-Token": cfg.vigil_worker_token} if cfg.vigil_worker_token else {}
    try:
        body = req.model_dump()
        body["offline"] = True   # cloud worker has no OpenAlice
        with httpx.Client(timeout=30, headers=hdr) as c:
            r = c.post(f"{base}/jobs", json=body)
            if r.status_code == 409:
                JOB["error"] = "Cloud worker is busy with another job."
                return
            r.raise_for_status()
            jid = r.json()["job_id"]
            _on_status(f"Submitted to cloud worker ({jid})...")
            while True:
                s = c.get(f"{base}/jobs/{jid}").json()
                JOB["stage_text"] = s.get("stage_text", "running")
                _on_status_passthrough(s.get("stage_text", ""))
                if s.get("status") in {"done", "completed", "finished", "error", "failed"}:
                    if s.get("error"):
                        JOB["error"] = f"Cloud: {s['error']}"
                    else:
                        res = c.get(f"{base}/jobs/{jid}/result").json()
                        (OUTPUTS_DIR / "latest.json").write_text(json.dumps(res, default=str))
                        JOB["result"] = "latest.json"
                    return
                _t.sleep(2)
    except Exception as exc:  # noqa: BLE001
        logger.exception("remote job failed")
        JOB["error"] = f"Cloud worker unreachable: {exc}"
    finally:
        JOB["running"] = False
        JOB["stage"] = JOB["total"]


def _on_status_passthrough(msg: str) -> None:
    if msg and (not JOB["log"] or JOB["log"][-1] != msg):
        _on_status(msg)


@app.post("/api/calibrate")
def start_calibrate() -> dict:
    if JOB["running"]:
        raise HTTPException(status_code=409, detail="A job is already running.")
    _reset_job("calibrate", "calibration")
    threading.Thread(target=_run_calibrate_job, daemon=True).start()
    return {"started": True}


class PortfolioAdd(BaseModel):
    symbol: str
    name: str = ""
    entry_price: float | None = None
    qty: float | None = None
    note: str = ""
    asset_class: str = ""
    entry_date: str = ""


class ReportInboxPush(BaseModel):
    item: dict
    directive: str = ""


@app.get("/api/portfolio")
def portfolio_list() -> dict:
    from scanner.portfolio import PortfolioStore
    return {"portfolio": PortfolioStore().list()}


@app.post("/api/portfolio/add")
def portfolio_add(req: PortfolioAdd) -> dict:
    from scanner.portfolio import PortfolioStore
    rec = PortfolioStore().add(
        req.symbol, entry_price=req.entry_price, qty=req.qty,
        note=req.note, name=req.name, asset_class=req.asset_class,
        entry_date=req.entry_date)
    return {"added": rec}


@app.get("/api/portfolio/performance")
async def portfolio_performance() -> dict:
    from scanner.portfolio import PortfolioStore
    return await PortfolioStore().performance()


@app.post("/api/portfolio/remove")
def portfolio_remove(symbol: str) -> dict:
    from scanner.portfolio import PortfolioStore
    return {"removed": PortfolioStore().remove(symbol)}


@app.post("/api/portfolio/check")
def portfolio_check() -> dict:
    if JOB["running"]:
        raise HTTPException(status_code=409, detail="A job is already running.")
    _reset_job("portfolio-check", "portfolio sell-check")

    def _job():
        from scanner.signals import portfolio_sell_check
        try:
            _on_status("Forecasting your portfolio for sell signals...")
            asyncio.run(portfolio_sell_check())
            _on_status("Portfolio sell-check complete.")
        except Exception as exc:  # noqa: BLE001
            JOB["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            JOB["running"] = False
            JOB["stage"] = JOB["total"]

    threading.Thread(target=_job, daemon=True).start()
    return {"started": True}


@app.post("/api/inbox/report")
async def push_report_to_inbox(req: ReportInboxPush) -> dict:
    """Push one selected report into OpenAlice Inbox for follow-up."""
    cfg = get_config()
    item = req.item or {}
    report = item.get("report") or {}
    symbol = item.get("symbol") or report.get("symbol") or "Unknown"
    title = f"Vigil pick: {symbol}"
    markdown = _report_markdown(item, req.directive)
    try:
        async with OpenAliceClient(cfg.openalice_mcp_url) as oa:
            ok = await oa.push_inbox(title=title, markdown=markdown, payload={
                "type": "vigil.report",
                "symbol": symbol,
                "directive": req.directive,
                "watchlist_item": item,
            })
    except Exception as exc:  # noqa: BLE001
        logger.warning("single-report Inbox push failed: %s", exc)
        ok = False
    if not ok:
        raise HTTPException(status_code=502, detail="OpenAlice Inbox push failed.")
    return {"ok": True}


@app.get("/api/status")
def status() -> dict:
    return {k: JOB[k] for k in (
        "running", "kind", "stage", "total", "stage_text", "log",
        "result", "error", "started_at", "directive")}


def _report_markdown(item: dict, directive: str) -> str:
    report = item.get("report") or {}
    symbol = item.get("symbol") or report.get("symbol") or "Unknown"
    name = item.get("name") or report.get("name") or ""
    exp = item.get("expected_return_pct")
    exp_s = f"{exp:+.1f}%" if isinstance(exp, (int, float)) else "n/a"
    prob = item.get("prob_up")
    prob_s = f"{prob * 100:.0f}%" if isinstance(prob, (int, float)) else "n/a"
    reasons = report.get("reasons") or []
    risks = report.get("risks") or []
    lines = [
        f"# Vigil Pick: {symbol} {name}".strip(),
        "",
        f"Directive: {directive or '(not specified)'}",
        f"Strategy: {item.get('strategy_type') or report.get('strategy_type') or 'n/a'}",
        f"Horizon: {item.get('horizon') or report.get('horizon') or 'n/a'}",
        f"Kronos expected return: {exp_s}",
        f"Probability up: {prob_s}",
        f"Risk/reward: {item.get('risk_reward') or report.get('risk_reward') or 'n/a'}",
        "",
        "## Thesis",
        report.get("thesis", ""),
        "",
        "## Why now",
        *[f"- {r}" for r in reasons],
        "",
        "## Strategy",
        f"- Entry: {report.get('entry_zone', 'n/a')}",
        f"- Stop: {report.get('stop_loss', 'n/a')}",
        f"- Target: {report.get('target', 'n/a')}",
        "",
        "## Risks",
        *[f"- {r}" for r in risks],
    ]
    return "\n".join(lines)


@app.get("/api/outputs")
def list_outputs() -> dict:
    items = []
    for f in sorted(OUTPUTS_DIR.glob("watchlist_*.json"), reverse=True):
        try:
            wl = json.loads(f.read_text())
            items.append({
                "file": f.name,
                "generated_at": wl.get("generated_at"),
                "directive": wl.get("directive"),
                "count": len(wl.get("watchlist", [])),
                "provider": wl.get("provider"),
            })
        except Exception:  # noqa: BLE001
            continue
    return {"outputs": items}


def _pull_cloud_latest() -> bool:
    """Best-effort: copy the cloud worker's most recent result to local latest.json.
    This is what makes a scan you started and walked away from show up next time
    you open Vigil — even if the Mac was closed when the cloud finished."""
    cfg = get_config()
    if not cfg.vigil_worker_url:
        return False
    try:
        hdr = {"X-Vigil-Token": cfg.vigil_worker_token} if cfg.vigil_worker_token else {}
        with httpx.Client(timeout=15, headers=hdr) as c:
            r = c.get(f"{cfg.vigil_worker_url.rstrip('/')}/result/latest")
        if r.status_code == 200:
            OUTPUTS_DIR.mkdir(exist_ok=True)
            (OUTPUTS_DIR / "latest.json").write_text(json.dumps(r.json(), default=str))
            logger.info("Synced latest result from cloud worker")
            return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("cloud latest sync failed: %s", exc)
    return False


@app.get("/api/watchlist")
def get_watchlist(file: str = "latest") -> JSONResponse:
    # 'board' = today's combined daily board: prefer the cloud worker's copy (the
    # buckets run there), fall back to a locally built one.
    if file == "board":
        cfg = get_config()
        if cfg.vigil_worker_url:
            try:
                hdr = {"X-Vigil-Token": cfg.vigil_worker_token} if cfg.vigil_worker_token else {}
                with httpx.Client(timeout=15, headers=hdr) as c:
                    r = c.get(f"{cfg.vigil_worker_url.rstrip('/')}/result/board")
                if r.status_code == 200:
                    return JSONResponse(r.json())
            except Exception:  # noqa: BLE001
                pass
        daily = OUTPUTS_DIR / "daily"
        boards = sorted(daily.glob("*/combined.json"), reverse=True) if daily.exists() else []
        if boards:
            return JSONResponse(json.loads(boards[0].read_text()))
        raise HTTPException(status_code=404, detail="no daily board yet")
    name = "latest.json" if file in ("latest", "", None) else Path(file).name
    # When asking for 'latest' and not mid-scan, refresh from the cloud worker so
    # results that finished while the Mac was off still appear.
    if name == "latest.json" and not JOB["running"]:
        _pull_cloud_latest()
    path = OUTPUTS_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return JSONResponse(json.loads(path.read_text()))


# ── index ticker tape (old-school running quotes) ──────────────────────────
_TICKER = [
    ("SPY", "S&P 500"), ("QQQ", "Nasdaq 100"), ("DIA", "Dow 30"), ("IWM", "Russell 2000"),
    ("EWU", "FTSE 100"), ("EWG", "DAX"), ("EWQ", "CAC 40"), ("FEZ", "Euro Stoxx 50"),
    ("EWJ", "Japan"), ("MCHI", "China"), ("INDA", "India"),
    # Commodities show the FRONT-MONTH FUTURES price (what "gold"/"oil price"
    # actually means), not the ETF proxy: GC=F = COMEX gold, CL=F = WTI crude.
    ("GC=F", "Gold"), ("CL=F", "WTI Crude"), ("BTCUSD", "Bitcoin"),
]
_ticker_cache: dict = {"ts": 0.0, "data": None}


@app.get("/api/ticker")
async def ticker() -> dict:
    """Last close + day change for the index/asset ETFs shown in the tape. Cached
    10 min so page loads don't hammer Yahoo."""
    import time as _t
    if _ticker_cache["data"] and _t.time() - _ticker_cache["ts"] < 600:
        return _ticker_cache["data"]
    from scanner import market_data

    async def one(sym: str, label: str):
        try:
            rows = await market_data.fallback_ohlcv(sym, bars=6)
        except Exception:  # noqa: BLE001
            return None
        closes = [r.get("close") for r in (rows or []) if r.get("close") is not None]
        if len(closes) < 2:
            return None
        last, prev = closes[-1], closes[-2]
        chg = ((last / prev - 1) * 100) if prev else None
        return {"symbol": sym, "label": label, "last": round(last, 2),
                "change_pct": round(chg, 2) if chg is not None else None}

    import asyncio as _a
    res = await _a.gather(*[one(s, l) for s, l in _TICKER])
    data = {"items": [r for r in res if r]}
    _ticker_cache.update(ts=_t.time(), data=data)
    return data


@app.get("/api/health")
async def health() -> dict:
    cfg = get_config()
    oa = await _probe(cfg.openalice_mcp_url)
    kr = await _probe(f"{cfg.kronos_service_url}/health")
    return {
        "ok": True, "provider": cfg.llm_provider,
        "openalice": oa, "kronos": kr,
        "openalice_url": cfg.openalice_mcp_url,
    }


async def _probe(url: str) -> bool:
    # A returned response (even 4xx/405) means the server is up. Any raised
    # exception — including ConnectError — means it is not reachable.
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.get(url)
        return True
    except Exception:  # noqa: BLE001
        return False


# ── static ─────────────────────────────────────────────────────────────────
@app.get("/")
def index() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")


app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")
app.mount("/ui", StaticFiles(directory=str(UI_DIR)), name="ui")


def main() -> None:
    import uvicorn
    port = CFG.ui_port
    url = f"http://127.0.0.1:{port}"
    logger.info("Scanner control panel -> %s", url)
    if CFG.refresh_on_open:
        logger.info("VIGIL_REFRESH_ON_OPEN=true; starting background signal refresh")
        threading.Thread(target=_refresh_on_open_job, daemon=True).start()
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def _refresh_on_open_job() -> None:
    try:
        from scanner.signals import run_signals
        asyncio.run(run_signals(get_config().signal_market_list))
    except Exception as exc:  # noqa: BLE001
        logger.warning("refresh-on-open signal run failed: %s", exc)


if __name__ == "__main__":
    main()
