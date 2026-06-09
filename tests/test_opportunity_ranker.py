from scanner import opportunity_ranker as OR


def test_speculative_can_rank_countertrend_high_without_score_penalty():
    item = {
        "score": 70,
        "direction": "long",
        "expected_return_pct": 12,
        "ret_q95_pct": 30,
        "ret_q05_pct": -8,
        "terminal_vol_pct": 18,
        "risk_reward": "1:4",
        "tags": ["counter_trend"],
        "report": {
            "_sizing": {"p_win_used": 0.48, "expected_r": 0.6, "weight_pct": 4},
            "_barrier": {"expected_r": 0.6},
            "_ta": {"rr_value": 4},
        },
    }
    out = OR.score_item(item)
    assert out["best_profile"] in {"aggressive", "speculative"}
    assert out["profiles"]["speculative"]["score"] > out["profiles"]["conservative"]["score"]


def test_apply_ranks_assigns_profile_ranks():
    conservative = {
        "score": 75, "expected_return_pct": 3, "terminal_vol_pct": 5,
        "tags": [], "report": {"_sizing": {"p_win_used": 0.65, "expected_r": 0.5, "weight_pct": 8},
                                "_ta": {"rr_value": 2}},
    }
    speculative = {
        "score": 55, "expected_return_pct": 15, "ret_q95_pct": 35,
        "terminal_vol_pct": 25, "tags": ["counter_trend"],
        "report": {"_sizing": {"p_win_used": 0.45, "expected_r": 0.4, "weight_pct": 2},
                   "_ta": {"rr_value": 5}},
    }
    items = [conservative, speculative]
    OR.apply_ranks(items)
    assert conservative["opportunity"]["profiles"]["conservative"]["rank"] == 1
    assert speculative["opportunity"]["profiles"]["speculative"]["rank"] == 1
