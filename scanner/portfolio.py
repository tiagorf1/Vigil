"""Local portfolio store.

A simple JSON file of positions you choose to track — built by moving names out
of a watchlist. Independent of OpenAlice: works offline. Vigil forecasts these
holdings on every scan (and in the signals job) and warns you when a held name's
forecast turns negative.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from scanner.config import get_config

logger = logging.getLogger("scanner.portfolio")


class PortfolioStore:
    def __init__(self):
        cfg = get_config()
        self.path = cfg.project_root / "portfolio.json"

    def _read(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, list) else []
        except Exception:  # noqa: BLE001
            return []

    def _write(self, items: list[dict]) -> None:
        self.path.write_text(json.dumps(items, indent=2, default=str))

    def list(self) -> list[dict]:
        return self._read()

    def symbols(self) -> list[str]:
        return [p["symbol"] for p in self._read() if p.get("symbol")]

    def add(self, symbol: str, entry_price=None, qty=None, note: str = "",
            name: str = "", asset_class: str = "equity") -> dict:
        symbol = symbol.strip().upper()
        items = self._read()
        existing = next((p for p in items if p["symbol"] == symbol), None)
        record = {
            "symbol": symbol, "name": name, "asset_class": asset_class,
            "entry_price": entry_price, "qty": qty, "note": note,
            "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if existing:
            existing.update({k: v for k, v in record.items() if v not in (None, "")})
        else:
            items.append(record)
        self._write(items)
        logger.info("Portfolio: added %s (%d holdings)", symbol, len(items))
        return record

    def remove(self, symbol: str) -> bool:
        symbol = symbol.strip().upper()
        items = self._read()
        new = [p for p in items if p["symbol"] != symbol]
        self._write(new)
        return len(new) != len(items)

    def asset_class_of(self, symbol: str) -> str:
        symbol = symbol.strip().upper()
        for p in self._read():
            if p["symbol"] == symbol:
                return p.get("asset_class", "equity")
        return "equity"
