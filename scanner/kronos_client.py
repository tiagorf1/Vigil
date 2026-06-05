"""Client for the local Kronos forecast service.

Starts the FastAPI service as a subprocess if it is not already healthy, then
POSTs OHLCV histories to /forecast. The service keeps the model warm so this is
cheap to call repeatedly within a scan.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import time

import httpx

from scanner.config import get_config

logger = logging.getLogger("scanner.kronos")


class KronosServiceError(RuntimeError):
    """Raised only when the service cannot be started at all (abort condition)."""


class KronosClient:
    def __init__(self):
        self.cfg = get_config()
        self.base_url = self.cfg.kronos_service_url
        self._proc: subprocess.Popen | None = None

    # ── service lifecycle ─────────────────────────────────────────────────
    async def ensure_service_running(self, timeout: float = 90.0) -> None:
        if await self._healthy():
            logger.info("Kronos service ready at %s", self.base_url)
            return

        if self.cfg.kronos_is_remote:
            # Offloaded to a remote host: we don't spawn it, just wait for it.
            deadline = time.time() + timeout
            while time.time() < deadline:
                if await self._healthy():
                    logger.info("Remote Kronos healthy at %s", self.base_url)
                    return
                await asyncio.sleep(2.0)
            raise KronosServiceError(
                f"Remote Kronos at {self.base_url} not reachable within {timeout:.0f}s")

        logger.info("Starting Kronos service on port %d ...", self.cfg.kronos_service_port)
        self._proc = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn", "kronos_service.main:app",
                "--port", str(self.cfg.kronos_service_port),
                "--log-level", "warning",
            ],
            cwd=str(self.cfg.project_root),
            env=os.environ.copy(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )

        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._proc.poll() is not None:
                raise KronosServiceError(
                    "Kronos service process exited during startup. Run "
                    "`uvicorn kronos_service.main:app --port "
                    f"{self.cfg.kronos_service_port}` manually to see the error."
                )
            if await self._healthy():
                logger.info("Kronos service healthy (model loaded)")
                return
            await asyncio.sleep(2.0)

        raise KronosServiceError(
            f"Kronos service did not become healthy within {timeout:.0f}s"
        )

    async def _healthy(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{self.base_url}/health")
                return r.status_code == 200 and r.json().get("status") == "ok"
        except Exception:  # noqa: BLE001
            return False

    def shutdown(self) -> None:
        """Stop the service if we started it."""
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            logger.info("Kronos service stopped")
        self._proc = None

    # ── inference ─────────────────────────────────────────────────────────
    async def forecast(
        self,
        symbol: str,
        ohlcv: list[dict],
        pred_len: int | None = None,
        sample_count: int | None = None,
    ) -> dict | None:
        if not ohlcv:
            logger.warning("%s: no OHLCV, skipping forecast", symbol)
            return None
        payload = {
            "symbol": symbol,
            "ohlcv": ohlcv,
            "pred_len": int(pred_len or self.cfg.default_pred_len),
            "sample_count": int(sample_count or self.cfg.kronos_sample_count),
        }
        try:
            t0 = time.time()
            async with httpx.AsyncClient(timeout=300.0) as client:
                r = await client.post(f"{self.base_url}/forecast", json=payload)
            if r.status_code != 200:
                logger.warning("%s: forecast HTTP %d — %s",
                               symbol, r.status_code, r.text[:200])
                return None
            data = r.json()
            logger.info("%s: forecast %+.2f%% (%.1fs)",
                        symbol, data.get("expected_return_pct", 0.0), time.time() - t0)
            return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s: forecast call failed: %s", symbol, exc)
            return None

    async def forecast_batch(
        self,
        items: list[dict],
        pred_len: int | None = None,
        n_paths: int | None = None,
    ) -> dict[str, dict]:
        """Forecast many symbols in one batched GPU pass.

        `items`: [{"symbol": str, "ohlcv": [...]}, ...].
        Returns {symbol: forecast_dict} for the symbols that succeeded.
        """
        items = [it for it in items if it.get("ohlcv")]
        if not items:
            return {}
        payload = {
            "items": [{"symbol": it["symbol"], "ohlcv": it["ohlcv"]} for it in items],
            "pred_len": int(pred_len or self.cfg.default_pred_len),
            "n_paths": int(n_paths or self.cfg.kronos_mc_paths),
        }
        try:
            t0 = time.time()
            async with httpx.AsyncClient(timeout=600.0) as client:
                r = await client.post(f"{self.base_url}/forecast_batch", json=payload)
            if r.status_code != 200:
                logger.warning("batch forecast HTTP %d — %s", r.status_code, r.text[:200])
                return {}
            results = r.json().get("results", [])
            out: dict[str, dict] = {}
            for res in results:
                if res and not res.get("error"):
                    out[res["symbol"]] = res
                elif res and res.get("error"):
                    logger.info("%s: forecast skipped (%s)", res.get("symbol"), res["error"])
            logger.info("Batch forecast: %d/%d symbols in %.1fs",
                        len(out), len(items), time.time() - t0)
            return out
        except Exception as exc:  # noqa: BLE001
            logger.warning("batch forecast call failed: %s", exc)
            return {}
