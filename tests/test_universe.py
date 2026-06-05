import pytest

from scanner.universe import UniverseBuilder


class FakeClient:
    async def search_symbols(self, directive, asset_class="equity"):
        return [
            {"symbol": "AAPL"},
            {"symbol": "NOTTRADEABLE"},
            {"symbol": "MSFT"},
        ]


@pytest.mark.asyncio
async def test_search_universe_filters_non_tradeable_symbols(monkeypatch):
    async def fake_resolve_many(symbols):
        return {
            "AAPL": {"valid": True},
            "NOTTRADEABLE": {"valid": False},
            "MSFT": {"valid": True},
        }

    monkeypatch.setattr("scanner.universe.resolve_many", fake_resolve_many)

    symbols = await UniverseBuilder(FakeClient()).build("quality software", "equity")

    assert symbols == ["AAPL", "MSFT"]


@pytest.mark.asyncio
async def test_explicit_symbols_skip_remote_validation(monkeypatch):
    async def fail_if_called(symbols):
        raise AssertionError("explicit ticker directives should not call resolver")

    monkeypatch.setattr("scanner.universe.resolve_many", fail_if_called)

    symbols = await UniverseBuilder(FakeClient()).build("AAPL MSFT", "equity")

    assert symbols == ["AAPL", "MSFT"]


@pytest.mark.asyncio
async def test_explicit_futures_and_forex_symbols():
    symbols = await UniverseBuilder(FakeClient()).build("GC=F EURUSD=X", "commodity")

    assert symbols == ["GC=F", "EURUSD=X"]


@pytest.mark.asyncio
async def test_commodity_and_forex_seed_universes():
    commodities = await UniverseBuilder(FakeClient()).build("", "commodity")
    forex = await UniverseBuilder(FakeClient()).build("", "forex")

    assert "GC=F" in commodities and "CL=F" in commodities
    assert "EURUSD=X" in forex and "USDJPY=X" in forex


@pytest.mark.asyncio
async def test_index_directive_expands_to_component_companies(monkeypatch):
    async def fake_expand(directive):
        return ["AAPL", "MSFT", "NVDA"], ["SPY"]

    monkeypatch.setattr("scanner.universe.expand_index_directive", fake_expand)

    symbols = await UniverseBuilder(FakeClient()).build("s&p 500", "index")

    assert symbols == ["NVDA", "AAPL", "MSFT"]


@pytest.mark.asyncio
async def test_index_directive_uses_local_safety_cap(monkeypatch):
    async def fake_expand(directive):
        return ["ZZZ"] + [f"S{i}" for i in range(200)] + ["NVDA", "AAPL"], ["SPY"]

    monkeypatch.setattr("scanner.universe.expand_index_directive", fake_expand)

    symbols = await UniverseBuilder(FakeClient()).build("s&p 500", "index")

    assert len(symbols) == 120
    assert symbols[:2] == ["NVDA", "AAPL"]
