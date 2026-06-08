# Unlocking Full Kronos + Yahoo

Kronos gives us, per symbol, a Monte-Carlo CLOUD of full OHLCV paths over H steps.
Today we read ONE number from it (close direction). Below is everything else the
cloud contains. Features are cheap post-processing of the paths; the only real
cost is PATH COUNT, so: screen with few paths, full-extract on finalists.

## A. Direction / return  (IMPLEMENTED)
- expected return, prob_up (blend), quantile cone. Calibrated.

## B. Volatility & range  (mostly UNUSED — highest-confidence Kronos signal)
- **Predicted realized vol** (std of path returns) per horizon. Vol is far more
  forecastable than direction. -> sizing, stop distance, regime.
- **Expected period range** (mean high-low) -> realistic stop/target widths.
- **Vol term structure** (10/30/60) -> vol expanding vs contracting -> breakout vs calm.
- **Predicted vol vs IMPLIED vol** (Yahoo options) -> vol risk premium: options
  rich (sell premium) or cheap (buy). Core options edge.

## C. Path-dependent / barrier probabilities  (UNUSED — best for entry/exit)
- **P(touch target before stop)** -> the REAL probability behind an R:R.
- **P(stop hit)** within horizon -> risk of being stopped out.
- **Expected Max Adverse Excursion** (worst dip on the path) -> smarter stop placement.
- **Expected Max Favorable Excursion** -> realistic profit-taking level.
- **Time-to-target** distribution -> how long the trade likely takes.
- **P(hit a specific level)** (e.g. a resistance) -> breakout odds.

## D. Distribution shape  (UNUSED)
- **Skew** of terminal returns -> asymmetric payoff (fat upside?).
- **CVaR / expected shortfall** (mean of worst 5% paths) -> true downside.
- **P(return > X%)** for any threshold -> upside capture, option moneyness.
- **Kurtosis / fat tails** -> blow-off / crash risk.

## E. Volume  (UNUSED)
- **Predicted volume trend** -> participation; a breakout on rising predicted
  volume is stronger than one on falling volume.

## F. Pattern on the predicted path  (UNUSED)
- Does the **median path break a TA level** (support/resistance) inside the
  horizon? -> forecast-confirmed breakout, the cleanest signal.
- **Predicted pullback-then-resume** -> entry TIMING (wait for the dip).
- **Predicted swing points** -> where to add/scale.

## G. Cross-sectional / relative  (UNUSED)
- **Risk-adjusted rank** = expected return / predicted vol (Sharpe-like screen).
- **Forecast dispersion across the universe** -> breadth / risk-on-off regime.
- **Predicted-path correlation** -> diversification + pairs (long A / short B).

## H. Options  (UNUSED — your future goal, Kronos fits perfectly)
- **P(price > strike)** at expiry per strike -> moneyness probabilities.
- **Expected move** -> straddle/strangle pricing, strike selection.
- **Kronos vol vs implied vol** -> buy/sell premium decision.
- **Probability of profit** for a spread, from the path cloud.

## I. Confidence / ensemble  (PARTLY USED)
- **Path agreement / dispersion** -> confidence (used in horizon select).
- **Kronos-small vs Kronos-base agreement** -> meta-confidence.
- Calibration layer adjusts all of the above to be honest.

---

# Yahoo endpoints (maximum information)
| Endpoint | Gives | Status |
|---|---|---|
| `v8/finance/chart` | OHLCV daily + **intraday 1m/5m** | used (daily); intraday UNUSED |
| `v10/finance/quoteSummary` | snapshot fundamentals | used |
| `ws/fundamentals-timeseries` | **historical** financials, KEYLESS | UNUSED (the no-key history fix) |
| `v7/finance/options` | **option chain: implied vol, strikes, OI, expiries** | UNUSED (needs crumb we have) |
| `ws/insights` | Yahoo's technical events, S/R, valuation flags | UNUSED |
| `v6/finance/recommendationsbysymbol` | peer/similar tickers | UNUSED (pairs/peers) |
| `v1/finance/search` | names + news | used (names) |

Intraday bars unlock real short-horizon (day-trade) Kronos forecasts. Options
chain + Kronos vol = the options engine. fundamentals-timeseries = keyless history.

---

# Compute architecture (cheap, on-demand, you stay in control)
PRINCIPLE: two lanes. (1) scheduled auto-signals = narrow universe, few paths.
(2) on-demand DEEP analysis (you pick what) = full paths + full feature set,
run on the cloud, results back to UI or Telegram.

## Cloud options (cheapest first)
1. **Oracle Cloud Always-Free ARM** (4 cores / 24 GB, $0 forever) — runs the
   worker + Kronos (CPU) + Telegram bot 24/7. The always-on BACKBONE. Handles
   scheduled signals AND your on-demand requests. Free.
2. **Modal (serverless GPU)** — ~$30/mo free credit, then pay-per-SECOND (T4 ~
   $0.0002/s). Spins up only when you submit a job; a full deep scan costs cents.
   PERFECT for "analyze X now" bursts. No idle cost.
3. **RunPod / Vast.ai spot GPU** (~$0.2-0.4/hr) — for the heaviest batch (full
   index components, 500 paths, all features). Start, run, stop.
4. **Local Mac** — fine for a few names on demand; full extraction x many names x
   3 horizons x 500 paths is the ~2h brick. Mitigate by: cache forecasts, screen
   with 24 paths, full-extract (500 paths) only the ~10 finalists.

## How you keep control (not full-auto)
- **worker.py** already exposes a job API (POST /jobs). Run it on Oracle-Free.
- The **UI "Run scan"** posts your chosen directive as a job to the worker; the
  Mac just renders results (no local compute). You choose what, when.
- The **Telegram bot** /deep <tickers> submits an on-demand job to the worker.
- Heaviest jobs: worker forwards to Modal/RunPod, returns when done.
- Auto-signals keep firing on schedule in parallel. You never lose the "I decide
  what to analyze" control; the compute just isn't on your Mac.

RECOMMENDED: Oracle-Free backbone (free, always-on) + Modal for burst (cents) +
local Mac for quick 1-3 name checks. Point the Mac UI + Telegram at the worker.
