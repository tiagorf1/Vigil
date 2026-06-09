"""Tests for the financial-coherence invariant layer."""

from scanner import sanity


def _clean_long():
    return {
        "direction": "long", "conviction": 4, "_score": 70,
        "_ta": {"entry_value": 100, "stop_value": 95, "target_value": 110, "rr_value": 2.0},
        "_barrier": {"p_target_first": 0.5, "p_stop_first": 0.2, "p_neither": 0.3},
        "_sizing": {"weight_pct": 10.0, "binding": "kelly"},
        "_score_breakdown": {"direction_prob": 60.0},
    }


def _fc_long():
    return {"prob_up": 0.6, "ret_q05_pct": -5, "ret_q50_pct": 2, "ret_q95_pct": 9}


def test_clean_pick_has_no_violations():
    assert sanity.audit(_clean_long(), _fc_long()) == []


def test_long_with_inverted_levels_flagged():
    rep = _clean_long()
    rep["_ta"] = {"entry_value": 100, "stop_value": 110, "target_value": 95, "rr_value": 2.0}
    out = sanity.audit(rep, _fc_long())
    assert any(v["check"] == "levels" for v in out)


def test_barrier_not_summing_to_one_flagged():
    rep = _clean_long()
    rep["_barrier"] = {"p_target_first": 0.5, "p_stop_first": 0.5, "p_neither": 0.5}
    out = sanity.audit(rep, _fc_long())
    assert any(v["check"] == "barrier" for v in out)


def test_no_edge_with_weight_flagged():
    rep = _clean_long()
    rep["_sizing"] = {"weight_pct": 25.0, "binding": "no_edge"}
    out = sanity.audit(rep, _fc_long())
    assert any(v["check"] == "sizing" for v in out)


def test_catches_the_directional_prob_bug():
    # The exact class of bug we fixed: a short whose direction score was NOT
    # computed as (1 - prob_up). This must be caught.
    rep = _clean_long()
    rep["direction"] = "short"
    rep["_ta"] = {"entry_value": 100, "stop_value": 105, "target_value": 90, "rr_value": 2.0}
    rep["_score_breakdown"] = {"direction_prob": 20.0}   # WRONG: used prob_up (0.2*100)
    out = sanity.audit(rep, {"prob_up": 0.2})
    assert any(v["check"] == "score" for v in out)
    # And the correct value passes.
    rep["_score_breakdown"] = {"direction_prob": 80.0}   # right: (1-0.2)*100
    assert not any(v["check"] == "score" for v in sanity.audit(rep, {"prob_up": 0.2}))


def test_unordered_quantiles_flagged():
    out = sanity.audit(_clean_long(), {"prob_up": 0.6, "ret_q05_pct": 9, "ret_q50_pct": 2, "ret_q95_pct": -5})
    assert any(v["check"] == "forecast" for v in out)
