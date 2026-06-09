import json

from scanner import config, paper


def test_paper_stats_prefers_sample_backed_generation(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_PROJECT_ROOT", tmp_path)
    config.get_config.cache_clear()
    out = tmp_path / "outputs"
    out.mkdir()
    rows = [
        {"status": "closed", "direction_correct": False, "realized_return_pct": -5.0,
         "conviction": 3, "calibration_generation": "legacy_unknown"},
        {"status": "closed", "direction_correct": True, "realized_return_pct": 2.0,
         "conviction": 4, "calibration_generation": "sample_backed"},
        {"status": "closed", "direction_correct": True, "realized_return_pct": 1.0,
         "conviction": 4, "calibration_generation": "sample_backed"},
    ]
    (out / "paper_trades.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    stats = paper.stats()
    assert stats["closed"] == 3
    assert stats["closed_scored"] == 2
    assert stats["legacy_closed"] == 1
    assert stats["hit_rate"] == 1.0

    config.get_config.cache_clear()
