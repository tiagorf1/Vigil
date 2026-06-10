import json
from types import SimpleNamespace

from scanner import daily_board


def _board(symbols, generated_at, directive):
    return {
        "generated_at": generated_at,
        "directive": directive,
        "total_scanned": 10,
        "total_screened": len(symbols),
        "provider": "none",
        "watchlist": [
            {
                "symbol": sym,
                "rank": i,
                "score": 70 - i,
                "opportunity": {"profiles": {"balanced": {"rank": i, "score": 80 - i}}},
                "report": {},
            }
            for i, sym in enumerate(symbols, start=1)
        ],
    }


def test_daily_board_combines_same_day_and_rewrites_bucket(tmp_path, monkeypatch):
    monkeypatch.setattr(daily_board, "get_config",
                        lambda: SimpleNamespace(project_root=tmp_path, llm_provider="none"))
    out = tmp_path / "outputs"
    out.mkdir()
    p1 = out / "watchlist_1.json"
    p2 = out / "watchlist_2.json"
    p1.write_text(json.dumps(_board(["SPY", "QQQ"], "2026-06-10T01:00:00+00:00", "us")))
    p2.write_text(json.dumps(_board(["GLD"], "2026-06-10T02:00:00+00:00", "commodities")))

    daily_board.ingest(p1, "US bucket")
    combined_path = daily_board.ingest(p2, "Commodity bucket")
    combined = json.loads(combined_path.read_text())

    assert combined["combined_board"] is True
    assert combined["board_date"] == "2026-06-10"
    assert {x["symbol"] for x in combined["watchlist"]} == {"SPY", "QQQ", "GLD"}
    assert (out / "latest.json").exists()

    p1.write_text(json.dumps(_board(["IWM"], "2026-06-10T03:00:00+00:00", "us")))
    daily_board.ingest(p1, "US bucket")
    refreshed = json.loads((out / "latest.json").read_text())
    assert {x["symbol"] for x in refreshed["watchlist"]} == {"IWM", "GLD"}


def test_daily_board_does_not_pull_yesterday(tmp_path, monkeypatch):
    monkeypatch.setattr(daily_board, "get_config",
                        lambda: SimpleNamespace(project_root=tmp_path, llm_provider="none"))
    out = tmp_path / "outputs"
    out.mkdir()
    old = out / "old.json"
    new = out / "new.json"
    old.write_text(json.dumps(_board(["OLD"], "2026-06-09T23:00:00+00:00", "old")))
    new.write_text(json.dumps(_board(["NEW"], "2026-06-10T01:00:00+00:00", "new")))

    daily_board.ingest(old, "Old bucket")
    daily_board.ingest(new, "New bucket")
    latest = json.loads((out / "latest.json").read_text())

    assert latest["board_date"] == "2026-06-10"
    assert [x["symbol"] for x in latest["watchlist"]] == ["NEW"]
