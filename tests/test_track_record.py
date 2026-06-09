import json

from scanner import config, track_record


def test_track_record_uses_backtest_and_paper(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_PROJECT_ROOT", tmp_path)
    config.get_config.cache_clear()
    track_record.reload()
    out = tmp_path / "outputs"
    out.mkdir()
    (out / "backtest.json").write_text(json.dumps({
        "scorecard": {
            "equity@10": {
                "n": 20,
                "hit_rate_debiased": 0.55,
                "hit_rate_raw": 0.5,
                "model_ci95_coverage": 0.9,
                "mae_pct": 4.2,
                "r2": 0.12,
                "shrink_factor": 0.3,
            }
        },
        "overall": {"n": 20, "hit_rate_debiased": 0.55},
    }))
    rows = []
    for i in range(5):
        rows.append({
            "status": "closed",
            "symbol": "AAPL",
            "asset_class": "equity",
            "horizon_days": 10,
            "predicted_return_pct": 4.0,
            "prob_up": 0.6,
            "direction_correct": i < 3,
            "realized_return_pct": 1.0,
            "conviction": 3,
        })
    (out / "paper_trades.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    rec = track_record.for_pick("AAPL", "equity", 10)
    assert rec["model"]["bucket"] == "equity@10"
    assert rec["model"]["direction_hit_rate"] == 0.55
    assert rec["model"]["cone_coverage"] == 0.9
    assert rec["vigil"]["closed"] == 5
    assert rec["vigil"]["hit_rate"] == 0.6

    track_record.reload()
    config.get_config.cache_clear()
