"""KronosClient request formatting and response parsing (mocked HTTP)."""

import httpx
import pytest

from scanner.kronos_client import KronosClient


class FakeResp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status
        self.text = str(data)

    def json(self):
        return self._data


class FakeAsyncClient:
    captured = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json):
        FakeAsyncClient.captured = {"url": url, "json": json}
        if url.endswith("/forecast_batch"):
            results = [{"symbol": it["symbol"], "expected_return_pct": 5.0,
                        "prob_up": 0.6} for it in json["items"]]
            return FakeResp({"results": results})
        return FakeResp({"symbol": json["symbol"], "expected_return_pct": 5.0})

    async def get(self, url):
        return FakeResp({"status": "ok"})


@pytest.mark.asyncio
async def test_forecast_empty_ohlcv_returns_none():
    client = KronosClient()
    assert await client.forecast("AAPL", []) is None


@pytest.mark.asyncio
async def test_forecast_payload_and_parse(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    client = KronosClient()
    ohlcv = [{"ts": "2024-01-01", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 10}]
    result = await client.forecast("AAPL", ohlcv)

    assert result["symbol"] == "AAPL"
    assert result["expected_return_pct"] == 5.0

    payload = FakeAsyncClient.captured["json"]
    assert payload["symbol"] == "AAPL"
    assert payload["ohlcv"] == ohlcv
    assert "pred_len" in payload and "sample_count" in payload
    assert FakeAsyncClient.captured["url"].endswith("/forecast")


@pytest.mark.asyncio
async def test_forecast_batch(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    # Pin to the plain HTTP path regardless of the developer's .env (which may
    # now have a serverless endpoint configured).
    monkeypatch.setenv("KRONOS_SERVERLESS_ENDPOINT", "")
    monkeypatch.setenv("RUNPOD_API_KEY", "")
    from scanner.config import get_config
    get_config.cache_clear()
    client = KronosClient()
    items = [
        {"symbol": "AAPL", "ohlcv": [{"close": 1}]},
        {"symbol": "MSFT", "ohlcv": [{"close": 2}]},
        {"symbol": "EMPTY", "ohlcv": []},  # filtered out before the call
    ]
    out = await client.forecast_batch(items)
    assert set(out) == {"AAPL", "MSFT"}
    assert out["AAPL"]["prob_up"] == 0.6
    payload = FakeAsyncClient.captured["json"]
    assert len(payload["items"]) == 2  # empty one dropped
    assert "n_paths" in payload
