"""Meta-model: feature vector + numpy logistic regression."""

import numpy as np

from scanner import meta_model as mm


def test_vec_length_and_safety():
    rec = {"predicted_return_pct": 5.0, "prob_up": 0.6, "fund_score": 70,
           "tech_score": 50, "conviction": 4, "features": {"ret_1m": 2.0, "rsi14": 55}}
    v = mm._vec(rec)
    assert len(v) == len(mm.FEATURES)
    assert all(isinstance(x, float) for x in v)
    # missing fields default to 0.0, never crash
    assert mm._vec({}) == [0.0] * len(mm.FEATURES)


def test_predict_proba_none_without_model(monkeypatch):
    monkeypatch.setattr(mm, "_load", lambda: None)
    assert mm.predict_proba({"prob_up": 0.6}) is None


def test_logistic_learns_separable():
    rng = np.random.default_rng(0)
    n = 200
    X = rng.normal(size=(n, 3))
    y = (X[:, 0] + 0.5 * X[:, 1] > 0).astype(float)  # separable-ish
    w, b, mu, sd = mm._fit_logistic(X, y, iters=600, lr=0.3)
    p = 1 / (1 + np.exp(-(((X - mu) / sd) @ w + b)))
    acc = ((p > 0.5) == (y > 0.5)).mean()
    assert acc > 0.8
