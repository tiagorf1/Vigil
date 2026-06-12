# HYPOTHESES.md

*Pre-registration is law. No test runs without a dated entry here first. Failed
entries are never deleted — the registered-to-confirmed ratio is the audit trail
against self-deception (the failure mode a solo researcher has no colleague to
catch). At most **two** hypotheses open (status `testing`) at a time.*

## The lab gate (promotion policy)
A signal is promoted from lab → product **only if**, in order:
1. **Pre-registered** here, before any test, with mechanism + predicted sign.
2. **Economically motivated** (a reason it should exist, not just a pattern).
3. **Significant after a multiple-testing (FDR) haircut**, with Newey–West (or
   strictly non-overlapping samples) for overlapping horizons.
4. **Positive *net* of costs** (spread + commission + slippage by cap/ADV bucket).
5. **Survives the holdout vault** (most recent ~18 months, one look ever).
6. **Live inputs available from free sources** (outlive WRDS graduation).
7. **Executable under `CONSTRAINTS.md`.**

On promotion, a **kill criterion** is written in the same commit (e.g. "rolling
12-month net IC < 0 for two consecutive quarters → demote to watch").

## Entry format
```
### H-NNN  <name>                                   [registered|testing|confirmed|rejected]
- Registered: YYYY-MM-DD
- Mechanism:        why this should produce returns
- Predicted sign:   + / -
- Universe:         e.g. US small/mid ex-microcap, price>$5, ADV floor
- Horizon:          e.g. 1 / 3 month forward
- Test:             metric + pass/fail threshold, decided NOW
- Production input:  the free-source data the live signal needs
- Result:           (filled after the one test) gross, net, FDR, holdout
- Kill criterion:   (on promotion)
```

---

## Registered candidates (priority order; none tested yet)

### H-001  PEAD on under-covered small caps            [registered]
- Registered: 2026-06-12
- Mechanism: post-earnings drift is strongest where limits-to-arbitrage are high
  — low coverage, small size, illiquidity — exactly where institutions can't chase.
- Predicted sign: + (high SUE → positive drift over weeks)
- Universe: US small/mid ex-microcap, price>$5, ADV floor; coverage-sorted.
- Horizon: 1–3 month forward, entry on the announcement.
- Test: long-short decile by SUE; net-of-cost IC and drift t-stat (NW) > 2 after FDR.
- Production input: earnings calendar + reported-vs-estimate (Finnhub/AV/Yahoo).
- Flagship: event-driven, long-side, capacity-constrained — fits Vigil's identity.

### H-002  Residual (idiosyncratic) momentum           [registered]
- Registered: 2026-06-12
- Mechanism: momentum on factor-model residuals survives post-publication better,
  less crowded, lower crash risk than raw 12-1 (which we already saw at t=1.74).
- Predicted sign: +
- Universe: US small/mid ex-microcap (S&P 500 as control only).
- Horizon: 1 month forward, monthly rebalance.
- Test: IC + decile spread, net of cost, NW, FDR; must beat raw-momentum baseline.
- Production input: prices only (free).

### H-003  Opportunistic insider buying (clustered)     [registered]
- Registered: 2026-06-12
- Mechanism: separate opportunistic from routine insiders (Cohen–Malloy–Pomorski);
  clustered opportunistic buys in small caps is a well-surviving long-only signal.
- Predicted sign: +
- Universe: US small/mid; EDGAR Form 4.
- Horizon: 1–3 month forward.
- Test: event-study CAR + portfolio IC, net of cost, FDR.
- Production input: EDGAR Form 4 (free forever — most durable pipeline; build parser early).

### H-004  Short interest as an exclusion filter        [registered]
- Registered: 2026-06-12
- Mechanism: high short interest predicts underperformance; can't short, but can
  refuse to be long it. Compounds with every long signal.
- Predicted sign: − (high SI → avoid long)
- Universe: US small/mid.
- Horizon: 1 month, bimonthly update.
- Test: does excluding top-SI decile improve the composite's net IC / drawdown?
- Production input: FINRA bimonthly short-interest file (free).

### H-005  Quality / gross profitability ballast        [registered]
- Registered: 2026-06-12
- Mechanism: Novy-Marx gross profitability in small caps; stabiliser + junk filter
  on the event signals, not a star alone.
- Predicted sign: +
- Universe: US small/mid.
- Horizon: quarterly.
- Test: as a composite leg — does it raise net Sharpe / cut drawdown?
- Production input: fundamentals (free, lagged correctly).

### H-006  Option-implied skew → equity cross-section   [registered]
- Registered: 2026-06-12
- Mechanism: steep OTM put skew predicts underperformance (Xing–Zhang–Zhao);
  informed traders act in options first. Signal only — buy the stock. Ties to thesis.
- Predicted sign: − (steep put skew → avoid/short-filter)
- Universe: liquid optionable US names.
- Horizon: 1 month.
- Test: IC on skew sort, net of cost, FDR; validate on OptionMetrics while WRDS lasts.
- Production input: self-recorded delayed option chains (start the nightly snapshot daemon now).

### H-007  FX/commodity trend (expectancy structure)    [registered]
- Registered: 2026-06-12
- Mechanism: the `forex@30` survivor was payoff asymmetry (cut losers/ride winners),
  i.e. the CTA premium — not direction skill. Diversifying sleeve, low equity correlation.
- Predicted sign: + (trend continuation via the chosen-stop engine)
- Universe: liquid FX (+ maybe commodity) via CFD.
- Horizon: ~1 month, time-series momentum.
- Test: net of **realistic CFD financing** (the thing most likely to kill it).
- Production input: prices (free); COT (H-008) as conditioning only.

### H-008  COT positioning extremes (conditioner)       [registered]
- Registered: 2026-06-12
- Mechanism: extreme large-spec positioning → reversal risk; documented but weak
  alone. Use only as a conditioning input on H-007.
- Production input: CFTC COT (free, weekly).
