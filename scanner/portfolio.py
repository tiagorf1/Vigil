"""Local portfolio store + paper-trading performance engine.

This IS your paper-trading benchmark. Enter a position with your own entry price
(and optional qty/date); Vigil treats it as held, forecasts it on every scan,
warns on sell signals, and tracks its live performance automatically.

CLI:
    python -m scanner.portfolio add AAPL --price 185.30 --qty 10 --date 2026-05-01
    python -m scanner.portfolio list
    python -m scanner.portfolio perf          # performance vs entry (+ SPY benchmark)
    python -m scanner.portfolio remove AAPL
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from scanner.config import get_config

logger = logging.getLogger("scanner.portfolio")


def infer_asset_class(symbol: str) -> str:
    s = symbol.upper()
    if s.endswith("=X"):
        return "forex"
    if s.endswith("=F"):
        return "commodity"
    if s.startswith("^"):
        return "index"
    if s.endswith(("USD", "USDT")):
        return "crypto"
    return "equity"


class PortfolioStore:
    def __init__(self):
        self.path = get_config().project_root / "portfolio.json"

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
            name: str = "", asset_class: str = "", entry_date: str = "") -> dict:
        symbol = symbol.strip().upper()
        items = self._read()
        existing = next((p for p in items if p["symbol"] == symbol), None)
        record = {
            "symbol": symbol,
            "name": name,
            "asset_class": asset_class or infer_asset_class(symbol),
            "entry_price": float(entry_price) if entry_price not in (None, "") else None,
            "qty": float(qty) if qty not in (None, "") else None,
            "note": note,
            "entry_date": entry_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if existing:
            existing.update({k: v for k, v in record.items() if v not in (None, "")})
            rec = existing
        else:
            items.append(record)
            rec = record
        self._write(items)
        logger.info("Portfolio: saved %s @ %s (%d holdings)",
                    symbol, record["entry_price"], len(items))
        return rec

    def remove(self, symbol: str) -> bool:
        symbol = symbol.strip().upper()
        items = self._read()
        new = [p for p in items if p["symbol"] != symbol]
        self._write(new)
        return len(new) != len(items)

    def asset_class_of(self, symbol: str) -> str:
        for p in self._read():
            if p["symbol"] == symbol.strip().upper():
                return p.get("asset_class") or infer_asset_class(symbol)
        return infer_asset_class(symbol)

    # ── paper-trading performance ──────────────────────────────────────────
    async def performance(self, benchmark: str = "SPY") -> dict:
        """Live performance of every holding vs its entry price + a benchmark."""
        from scanner.market_data import fallback_ohlcv
        holdings = self._read()
        positions, rets, days_list = [], [], []
        cost = value = realized_pnl = 0.0
        winners = losers = 0
        today = datetime.now(timezone.utc).date()

        for h in holdings:
            sym = h["symbol"]
            entry = h.get("entry_price")
            qty = h.get("qty")
            ohlcv = await fallback_ohlcv(sym, bars=5)
            cur = ohlcv[-1]["close"] if ohlcv else None
            ret = None
            pnl = None
            if entry and cur:
                ret = (cur / entry - 1) * 100
                rets.append(ret)
                winners += 1 if ret > 0 else 0
                losers += 1 if ret <= 0 else 0
                if qty:
                    pnl = (cur - entry) * qty
                    cost += entry * qty
                    value += cur * qty
                    realized_pnl += pnl
            days = None
            try:
                d0 = datetime.strptime(h.get("entry_date", ""), "%Y-%m-%d").date()
                days = (today - d0).days
                if days is not None:
                    days_list.append(days)
            except (ValueError, TypeError):
                pass
            positions.append({
                "symbol": sym, "name": h.get("name"),
                "asset_class": h.get("asset_class"),
                "entry_price": entry, "current_price": round(cur, 4) if cur else None,
                "qty": qty, "return_pct": round(ret, 2) if ret is not None else None,
                "pnl": round(pnl, 2) if pnl is not None else None,
                "days_held": days, "entry_date": h.get("entry_date"),
            })

        positions.sort(key=lambda p: (p["return_pct"] is None, -(p["return_pct"] or 0)))
        agg = {
            "n": len(holdings),
            "tracked": len(rets),
            "avg_return_pct": round(sum(rets) / len(rets), 2) if rets else None,
            "winners": winners, "losers": losers,
            "win_rate": round(winners / (winners + losers), 3) if (winners + losers) else None,
            "best": positions[0] if positions and positions[0]["return_pct"] is not None else None,
            "worst": next((p for p in reversed(positions) if p["return_pct"] is not None), None),
            "cost_basis": round(cost, 2) if cost else None,
            "market_value": round(value, 2) if value else None,
            "total_pnl": round(realized_pnl, 2) if realized_pnl else None,
            "total_return_pct": round((value / cost - 1) * 100, 2) if cost else None,
        }

        # Benchmark: SPY return over the median holding period.
        bench = None
        if days_list:
            md = int(sorted(days_list)[len(days_list) // 2])
            spy = await fallback_ohlcv(benchmark, bars=md + 10)
            if spy and len(spy) > md and md > 0:
                b_ret = (spy[-1]["close"] / spy[-md - 1]["close"] - 1) * 100
                bench = {"symbol": benchmark, "period_days": md,
                         "return_pct": round(b_ret, 2),
                         "alpha_pct": round((agg["avg_return_pct"] or 0) - b_ret, 2)
                         if agg["avg_return_pct"] is not None else None}

        return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "positions": positions, "aggregate": agg, "benchmark": bench}


def main() -> None:
    import argparse
    import asyncio
    ap = argparse.ArgumentParser(prog="scanner.portfolio")
    sub = ap.add_subparsers(dest="cmd")
    a = sub.add_parser("add")
    a.add_argument("symbol")
    a.add_argument("--price", type=float, default=None)
    a.add_argument("--qty", type=float, default=None)
    a.add_argument("--date", default="")
    a.add_argument("--name", default="")
    a.add_argument("--note", default="")
    r = sub.add_parser("remove"); r.add_argument("symbol")
    sub.add_parser("list"); sub.add_parser("perf")
    args = ap.parse_args()
    store = PortfolioStore()

    if args.cmd == "add":
        rec = store.add(args.symbol, entry_price=args.price, qty=args.qty,
                        entry_date=args.date, name=args.name, note=args.note)
        print(json.dumps(rec, indent=2))
    elif args.cmd == "remove":
        print("removed" if store.remove(args.symbol) else "not found")
    elif args.cmd == "perf":
        print(json.dumps(asyncio.run(store.performance()), indent=2, default=str))
    else:
        print(json.dumps(store.list(), indent=2, default=str))


if __name__ == "__main__":
    main()
