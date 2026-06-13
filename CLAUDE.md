# Vigil — Claude Code context

Vigil is an evidence-first equity research system for a small EU retail account
(internal package name: `scanner`). Two halves, one-way door between them:

- **The lab** — validates candidate signals with costs, point-in-time data,
  Newey–West t-stats, an FDR haircut, and a reserved holdout. It rejects most
  things. Nothing reaches the product until it clears the written gate.
- **The product** — a long/short, leverage-capable (T212 CFD) execution engine
  that harvests a *composite* of confirmed documented tilts, wrapped in the
  discipline layer that was always good: vol-target sizing, fractional Kelly, a
  single chosen stop, a paper-trade ledger, Telegram.

The earlier **Kronos** price-forecasting thesis was tested and **retired** — it
never beat naive baselines — and the forecast layer was excised. Do not
reintroduce price-forecasting as "the edge."

## Read these (kept in sync — single source of truth)
- `README.md` — what it is, how to run.
- `PROJECT_LOG.md` — the full honest history: what worked, what failed, the evidence.
- `REFINED_PLAN_v2.md` — the current plan (harden the lab, hunt under-covered small caps).
- `CONSTRAINTS.md` — the operator's reality (T212; long via Invest, long/short +
  leverage via CFD with financing; Portugal 28% tax; WRDS-to-May-2028
  lab/production split). **Check every hypothesis against it before coding.**
- `HYPOTHESES.md` — pre-registration log + the lab gate. Pre-register before testing.

## Method (non-negotiable)
- Hunt where a small account wins: under-covered small caps, event-driven, low turnover.
- WRDS (CRSP/IBES via `scanner.wrds_extract`, run locally with the user's login)
  *validates*; the live system runs only on free sources that outlive graduation
  (EDGAR, FINRA, free APIs).
- Every backtest reports **gross AND net of costs**; point-in-time universe;
  FDR haircut across factors tested; a reserved recent holdout (one look).
- Pre-register every hypothesis; never delete a failed one.

## Commands (macOS — use `python3`)
- `python3 -m scanner.factor_backtest` — cross-sectional IC + long/short net alpha
  (cost-aware, Newey–West, FDR, holdout). Local, no GPU.
- `python3 -m scanner.anomaly_study` — event/anomaly studies.
- `python3 -m scanner.wrds_extract crsp|ibes` — pull survivorship-free data (user's WRDS login).
- `python3 -m scanner.server` (or `Vigil.command`) — the cockpit.
- `PYTHONPATH=. python3 -m pytest -q` — tests.

Secrets live only in `.env` (gitignored). The GitHub repo `tiagorf1/Vigil` is public.
