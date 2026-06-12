# Vigil roadmap — the real-deal rebuild

Identity: **an honest, multi-factor execution engine that surfaces interesting
alpha choices daily** — documented edges + risk discipline, not a model oracle.
Process rule: hypothesis first → one pre-registered backtest → keep survivors.
Never "backtests galore" (data mining). Everything discovered exploratorily must
be confirmed out-of-sample (IC harness) before going live.

## Done
- Honest backtest harness: first-passage R, conditional buckets, cross-sectional,
  **Kronos-vs-naive baseline test** (the verdict: Kronos ~never beats naive).
- Calibration (de-bias + widen cones), vol-target + fractional-Kelly sizing.
- Mac-local cockpit + **serverless GPU** (scale-to-zero), Telegram signals.
- Factor library (`factors.py`) + cross-sectional **IC harness** (`factor_backtest.py`).
- Chosen single stop (trailing vs structural); minimal signal format; futures ticker.

## Next (user-prioritised: 1, 2, 3)
1. **Confirm cross-sectional momentum** on full S&P 500 / global (IC t-stat > 2).
   Live lead from first run (IC +0.044, 67% hit, underpowered at n=50).
2. **Regime awareness** — FRED/ALFRED point-in-time macro → growth×inflation
   quadrant + yield-curve (Treasury) + risk-on/off; re-weight factors by regime.
   Justified empirically: low_vol IC flipped negative in the 2021-26 high-beta era.
   Sources: FRED/ALFRED, US Treasury, Damodaran (valuation/ERP), Eurostat + UK ONS.
3. **CFTC COT positioning** — free weekly; the "what are big players doing" signal,
   best on FX / commodities / index futures (where price factors are thin).
   (Prime-brokerage data is NOT retail-accessible — COT is the public proxy.)

## Queued ideas (captured so nothing is lost)
- **Walk-forward full-pipeline replay** — run the whole live stack at a past date
  (only prior data), grade the picks, and analyse what the *actual* winners had in
  common (feature discovery). Hypothesis-generation only → confirm in IC harness.
- **Global breadth** — MSCI World / multi-market universe (cheap now: factors need
  no GPU). Like having other markets, not just SPY.
- **Confirmed-reversal detector** — reversals with confirmation (divergence/
  exhaustion), backtested as its own bucket. (Blind counter-trend loses — proven.)
- **Volume** — in the library (OBV momentum); test at shorter horizons / smaller caps.
- **News → PEAD** — post-earnings drift as the tradeable, documented form of the
  "what news moves what" idea; event-reaction reference table as later context.
- **SEC EDGAR** — 13F institutional flow + insider (Form 4) as factor inputs.
- **Daily-choices cockpit view** with the *why* + paper-trade → realized-performance loop.
- **Scheduling** (pre-market sweep, timezone cascade) — once a signal is confirmed.
- Risk-free rate into valuation models (low priority; Yahoo multiples embed it).

## Demoted / settled
- **Kronos** — does not beat naive baselines (only a faint forex@30 expectancy edge,
  not direction skill). Kept at most as a minor FX input / vol-cone visual.
- **"Pure vol plays"** — vol is predictable but naive trailing vol does it as well;
  use vol for sizing, not as a Kronos signal.
- **Options** — not executable for the user (tastytrade withdrawal issue) + vol edge naive.
- **Oracle box** — bypassed; Mac + serverless is the live path.
