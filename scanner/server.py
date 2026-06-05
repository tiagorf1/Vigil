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
    threading.Thread(target=_run_scan_job, args=(req,), daemon=True).start()
    return {"started": True}


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
    asset_class: str = "equity"


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
        note=req.note, name=req.name, asset_class=req.asset_class)
    return {"added": rec}


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


@app.get("/api/watchlist")
def get_watchlist(file: str = "latest") -> JSONResponse:
    name = "latest.json" if file in ("latest", "", None) else Path(file).name
    path = OUTPUTS_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return JSONResponse(json.loads(path.read_text()))


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
