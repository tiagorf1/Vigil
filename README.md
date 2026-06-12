# Vigil

A disciplined, evidence-first equity research system for a small EU retail
account — and a public derivatives-research portfolio piece.

Vigil has two halves, separated by a one-way door:

- **The lab** — a rigorous backtest/IC harness that validates candidate signals
  with costs, point-in-time data, and multiple-testing control, and *rejects*
  most of them. No signal reaches the product until it clears a written gate.
- **The product** — a long-only execution engine that harvests a *composite* of
  several weak, low-correlation, documented tilts (event drift, insider buying,
  residual momentum, quality, short-interest exclusion), wrapped in the part of
  Vigil that was always good: vol-target sizing, fractional Kelly, a single
  chosen stop, a forward paper-trade ledger, and Telegram alerts.

**What Vigil is *not*:** a daily oracle. An earlier version forecast prices with
a public transformer (Kronos) and built a product around it; a proper baseline
study showed it never beat naive baselines, so that thesis was retired. See
[`PROJECT_LOG.md`](PROJECT_LOG.md) for the full, honest history,
[`REFINED_PLAN_v2.md`](REFINED_PLAN_v2.md) for the current plan,
[`CONSTRAINTS.md`](CONSTRAINTS.md) for what this operator can actually trade, and
[`HYPOTHESES.md`](HYPOTHESES.md) for the pre-registered research log.

## Method (the non-negotiables)
- Hunt where a small account has structural advantage: under-covered small/mid-caps,
  event-driven drift, long-side, low turnover.
- WRDS (CRSP/Compustat/IBES/OptionMetrics) is a *research window* for validation;
  the live system runs only on data that outlives enrolment (EDGAR, FINRA, free APIs).
- Every backtest reports **gross and net of costs**; point-in-time universes;
  multiple-testing haircuts; an untouched recent holdout.
- Pre-register every hypothesis before testing; never delete a failed one.

## Run
```bash
python -m scanner.factor_backtest --horizon 21 --cuts 36   # cross-sectional IC (local, no GPU)
python -m scanner.anomaly_study --horizon 10               # event/anomaly studies
python -m scanner.server                                   # cockpit (or double-click Vigil.command)
```

Secrets live only in `.env` (gitignored). This repo is public.
