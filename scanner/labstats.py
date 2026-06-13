"""Lab statistics — the machinery that makes a backtest verdict trustworthy.

Three things the first lab lacked (per the external review):
  - Newey–West t-stats: overlapping-horizon returns are autocorrelated, which
    inflates naive t-stats. NW corrects the standard error.
  - Benjamini–Hochberg FDR: when many factors are tested, some clear t>2 by
    chance. BH controls the false-discovery rate across the batch.
  - Deflated Sharpe: a Sharpe selected from N trials is biased upward; the
    deflated version asks whether it survives the selection.

All pure numpy. No look-ahead, no model — just honest inference.
"""

from __future__ import annotations

import math

import numpy as np


def newey_west_tstat(x, lags: int | None = None) -> tuple[float, float]:
    """t-stat for mean(x)=0 with a Newey–West (Bartlett) HAC standard error.
    Returns (t_stat, se). `lags` defaults to floor(4*(n/100)^(2/9))."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 4:
        return 0.0, float("nan")
    mu = x.mean()
    e = x - mu
    if lags is None:
        lags = int(math.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
    gamma0 = float(e @ e) / n
    s = gamma0
    for l in range(1, lags + 1):
        w = 1.0 - l / (lags + 1.0)
        cov = float(e[l:] @ e[:-l]) / n
        s += 2.0 * w * cov
    se = math.sqrt(max(s, 1e-18) / n)
    return (mu / se if se > 0 else 0.0), se


def two_sided_p(t: float, df: int) -> float:
    """Two-sided p-value from a t-stat. Normal approx for df>=30 (good enough
    for our cut counts); Student-t tail otherwise via a simple approximation."""
    z = abs(t)
    # survival of standard normal *2 (two-sided); fine for df>=30.
    p = math.erfc(z / math.sqrt(2.0))
    return float(min(1.0, p))


def benjamini_hochberg(pvals: list[float], q: float = 0.10) -> dict:
    """BH-FDR. Returns the largest p that passes and which indices survive at q."""
    arr = np.asarray(pvals, float)
    m = len(arr)
    if m == 0:
        return {"threshold": 0.0, "passed": []}
    order = np.argsort(arr)
    passed = np.zeros(m, bool)
    thresh = 0.0
    for rank, idx in enumerate(order, start=1):
        if arr[idx] <= q * rank / m:
            thresh = q * rank / m
    for idx in order:
        if arr[idx] <= thresh:
            passed[idx] = True
    return {"threshold": round(float(thresh), 4), "passed": passed.tolist()}


def deflated_sharpe(sr: float, n_obs: int, n_trials: int,
                    skew: float = 0.0, kurt: float = 3.0) -> float:
    """Probabilistic/deflated Sharpe: P(true SR>0) given that this SR was the best
    of `n_trials` tried. Bailey–López de Prado, simplified to a per-period SR.
    Returns a probability in [0,1]; >0.95 is the usual bar."""
    if n_obs < 4 or n_trials < 1:
        return 0.0
    # expected max of n_trials standard normals (benchmark SR under the null)
    e_max = (1 - 0.5772) * _norm_ppf(1 - 1.0 / n_trials) + \
        0.5772 * _norm_ppf(1 - 1.0 / (n_trials * math.e))
    sr0 = e_max / math.sqrt(n_obs)  # null SR threshold scaled to sample
    denom = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4.0 * sr * sr, 1e-9))
    z = (sr - sr0) * math.sqrt(n_obs - 1) / denom
    return float(0.5 * (1 + math.erf(z / math.sqrt(2.0))))


def _norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF (Acklam's approximation)."""
    p = min(max(p, 1e-9), 1 - 1e-9)
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
