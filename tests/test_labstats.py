import numpy as np
from scanner import labstats as L

def test_newey_west_noise_insignificant():
    rng = np.random.default_rng(0)
    t, se = L.newey_west_tstat(rng.standard_normal(80) * 0.01)
    assert abs(t) < 2.0

def test_newey_west_real_signal():
    t, _ = L.newey_west_tstat(np.full(60, 0.01) + 0.001)  # constant positive
    assert t > 5

def test_benjamini_hochberg():
    bh = L.benjamini_hochberg([0.001, 0.04, 0.3, 0.6], q=0.10)
    assert bh["passed"][0] and not bh["passed"][3]

def test_deflated_sharpe_range():
    p = L.deflated_sharpe(0.4, 36, 5)
    assert 0.0 <= p <= 1.0
