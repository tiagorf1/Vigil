"""Watchlist sorting, capping, and serialisation."""

from scanner.output import WatchlistOutput


def _entry(symbol, conviction, exp, rr="1:2"):
    return {
        "report": {
            "symbol": symbol, "name": f"{symbol} Inc", "conviction": conviction,
            "strategy_type": "momentum", "risk_reward": rr, "timeframe": "2-4 weeks",
            "tags": ["t"], "thesis": "t", "fundamental_summary": "f",
            "technical_summary": "tech", "forecast_summary": "fc",
            "entry_zone": "$1", "stop_loss": "$0.9", "target": "$1.2",
            "risks": ["r1"],
        },
        "forecast": {"expected_return_pct": exp, "forecast_candles": [], "current_close": 10},
        "fund_score": 50, "tech_score": 60,
    }


def test_sort_by_conviction_then_return():
    entries = [
        _entry("A", 4, 5.0),
        _entry("B", 5, 3.0),
        _entry("C", 4, 8.0),
    ]
    wl = WatchlistOutput().build(entries, directive="test", total_scanned=10, total_screened=3)
    order = [x["symbol"] for x in wl["watchlist"]]
    assert order == ["B", "C", "A"]
    assert [x["rank"] for x in wl["watchlist"]] == [1, 2, 3]


def test_cap_at_max_watchlist_size():
    out = WatchlistOutput()
    entries = [_entry(f"S{i}", 3, float(i)) for i in range(out.cfg.max_watchlist_size + 10)]
    wl = out.build(entries, directive="t", total_scanned=30, total_screened=30)
    assert len(wl["watchlist"]) == out.cfg.max_watchlist_size


def test_markdown_contains_names():
    entries = [_entry("AAPL", 5, 8.3), _entry("NVDA", 4, 12.1)]
    out = WatchlistOutput()
    wl = out.build(entries, directive="tech", total_scanned=5, total_screened=2)
    md = out.to_markdown(wl)
    assert "AAPL" in md and "NVDA" in md
    assert "#1" in md
    assert "Thesis" in md


def _entry_sector(symbol, conviction, exp, sector):
    e = _entry(symbol, conviction, exp)
    e["sector"] = sector
    return e


def test_sector_diversification_cap():
    # 6 tech names plus enough other sectors that the 10-slot list can be filled
    # without exceeding 3 per sector -> the cap should bind for Technology.
    entries = [_entry_sector(f"T{i}", 5, float(i), "Technology") for i in range(6)]
    for sec in ("Energy", "Health", "Finance", "Materials"):
        entries += [_entry_sector(f"{sec}{i}", 5, 50.0 + i, sec) for i in range(2)]
    out = WatchlistOutput()
    wl = out.build(entries, directive="d", total_scanned=14, total_screened=14,
                   max_per_sector=3)
    sectors = [x["sector"] for x in wl["watchlist"]]
    assert sectors.count("Technology") <= 3
    assert len(wl["watchlist"]) == out.cfg.max_watchlist_size


def test_macro_and_exits_passthrough():
    wl = WatchlistOutput().build(
        [_entry("X", 3, 1.0)], directive="d", total_scanned=1, total_screened=1,
        macro={"DGS10": 4.2}, positions=[{"symbol": "X"}],
        exits=[{"symbol": "Y", "expected_return_pct": -3.0, "prob_up": 0.3}],
        benchmarks=[{"symbol": "SPY", "expected_return_pct": 1.2}])
    assert wl["macro"]["DGS10"] == 4.2
    assert wl["benchmarks"][0]["symbol"] == "SPY"
    assert wl["exits"][0]["symbol"] == "Y"
    assert wl["watchlist"][0]["held"] is True  # X is a held position


def test_required_watchlist_keys():
    wl = WatchlistOutput().build([_entry("X", 3, 1.0)], directive="d",
                                 total_scanned=1, total_screened=1)
    item = wl["watchlist"][0]
    for key in ("rank", "symbol", "name", "conviction", "strategy_type",
                "expected_return_pct", "risk_reward", "timeframe", "tags", "report",
                "opportunity"):
        assert key in item
    assert item["opportunity"]["profiles"]["balanced"]["rank"] == 1
    assert "generated_at" in wl and "provider" in wl
