# Vigil — Project Log

*The honest story, start to now: what we tried, what worked, what failed, where
we're going, and where it's hard. Internal package name is `scanner`; product
name is Vigil.*

---

## What Vigil is meant to be

A personal research tool that, every day, hands you a short list of **interesting,
asymmetric opportunities for alpha** — so you spend minutes choosing with
conviction instead of hours searching, trade with discipline, and eventually
get freed up for other work. A time-saver and a good-practice engine. The real
deal, explicitly *not* the magic-signal product daytraders sell.

---

## Act I — The original vision (OpenAlice + Kronos)

The first plan: a scanner that builds a universe, screens it, runs **Kronos**
(a transformer K-line price forecaster) on the survivors, has an LLM synthesise
each into a report, and outputs a ranked watchlist in a local UI. Market data
came from **OpenAlice** (a local MCP server). The thesis: *Kronos's forecasts are
the edge.*

## Act II — What got built (and it was a lot)

- **Kronos service** + batched probabilistic forecasting (Monte-Carlo path cloud
  → prob_up, quantile cone, forward vol, barrier probabilities).
- **Full pipeline**: universe → fundamental + technical screen → forecast →
  LLM report → ranked watchlist. Local indicators (RSI/MACD/SMA/ATR/BBands).
- **Honest-forecast layers**: deterministic invariant checks (`sanity.py`), an
  LLM critic, and empirical **calibration** (de-bias + widen the overconfident cone).
- **Risk/sizing**: vol-target + fractional-Kelly, binding-constraint logic.
- **Structure-based entry/exit** (`entry_exit.py`): trend filter, ADX, swing
  levels, a single chosen stop (trailing for trend trades, structural for reversals).
- **Cockpit UI** (FT-homage redesign), **Telegram signals**, world indexes,
  free Yahoo data fallback, a 24/7 GitHub-Actions cron.
- Rebranded **Scanner → Vigil**. ~109 unit tests.

By any engineering measure, the system was complete and polished.

## Act III — The reckoning (the model doesn't beat a coin and a calculator)

We built an honest backtest harness and asked the only question that matters:
**does Kronos beat naive baselines?** It does not.

- **Equity direction = noise.** Hit-rate ≈ 0.50; rank-corr ≈ 0. Trading Kronos's
  direction *loses* money where naive momentum *makes* it.
- **The "vol skill" was an illusion.** Kronos's equity vol-rank-corr of 0.58–0.68
  looked great — until naive 20-day trailing vol matched/beat it. Kronos reproduces
  "volatile stays volatile"; it doesn't predict vol *changes*.
- **FX was the one hope — and it didn't survive scale.** At n=48 Kronos crushed
  naive on FX direction (0.60 vs 0.42). At n=270 it evaporated to a coin flip. The
  only surviving cell in the entire study was `forex@30` *expectancy* (+0.18R vs ~0)
  — and that's a trade-structure effect, not direction skill.

Verdict: across every asset class and horizon, Kronos beat a free baseline in
**one cell**. The edge was never in the model. This is the central, hard-won
finding of the whole project.

## Act IV — The infrastructure odyssey (painful but resolved)

Getting compute right took longer than it should have, and taught real lessons:

- **OpenAlice** required a running local server and kept breaking scans → dropped
  in favour of free Yahoo data (`--offline`).
- **Oracle always-free box** as a 24/7 worker → its clone folder wasn't `~/Vigil`,
  so `git pull` silently never landed; it ran stale for days. Bypassed.
- **RunPod GPU pods** → left running idle, billed continuously (allocation, not
  utilisation), and burned ~$10. Lesson: *terminate, don't just stop using.*
- **RunPod Serverless** → the fix: scale-to-zero, $0 idle, nothing to terminate.
  Built handler + Dockerfile + a chunked async client. **Verified end-to-end.**
- **Silent `git push` failures** → `main` had no upstream and pushes were piped
  through `tail`, hiding the error; the box never got updates. Fixed (`-u origin main`).

**End state (clean):** the **Mac cockpit** runs the whole pipeline locally on free
data; only forecasting offloaded to **serverless GPU**; the box is bypassed. One
surface, $0 idle. And then — the factor pivot removed the need for GPU at all for
the core, making even serverless mostly vestigial.

## Act V — The strategy pivot (from oracle to execution engine)

If the edge isn't in a proprietary model, where is it? The honest answer quant
research settled long ago: **durable retail edge comes from documented edges
executed with discipline almost nobody maintains** — not a secret signal. So
Vigil's identity became: *an honest, multi-factor execution engine.* The compute
wasn't wasted — it bought a **research lab** (cheap, rigorous backtesting) and the
**certainty** of knowing what doesn't work.

We built a **factor library** (`factors.py`) and a cross-sectional **Information
Coefficient harness** (`factor_backtest.py`) — pure local, no GPU. Then tested
documented edges honestly:

- **Momentum (12-1):** right sign but **t-stat 1.74** on the full S&P 500, 36 cuts.
  Real but weak — the premium has been arbitraged thin (cf. McLean & Pontiff:
  anomalies lose ~58% of edge post-publication).
- **Low-vol:** **t-stat −2.21**, significantly *inverted* this era (high-beta tech
  led). The clearest empirical case for **regime awareness** — same factor, opposite
  sign by regime.
- Trend / short-reversal / volume-OBV: flat.

Then volatility-age anomaly studies (`anomaly_study.py`):
- **Overnight-drift:** absent in mega-caps this era (intraday ≈ overnight, both weak).
- **Vol-squeeze → outsized move:** *rejected* (squeezes precede *smaller* near-term
  moves — vol clusters). The coiled spring needs a trigger, not just compression.

Lesson from the negatives: **price/vol-pattern anomalies are efficient.** Outsized
moves come from **catalysts, flows, and positioning** (earnings, short squeezes,
index flows, regime shifts), not from price patterns. That's where to dig next.

## Act VI — Where we are now (2026-06)

- A clean, low-friction system: Mac cockpit + serverless, calibrated, with Telegram.
- A rigorous, free backtest/IC lab that kills bad ideas in minutes.
- A confirmed map of what *doesn't* work (Kronos, tired factors, price-only anomalies).
- A clear identity and roadmap; Kronos demoted, awaiting clean removal.
- **The core edge is still unfound.** That's the honest status.

---

## What worked

| | |
|---|---|
| **The honest backtest + IC harness** | The real asset. Tells the truth cheaply; killed every false hope. |
| **Serverless GPU** | Scale-to-zero, $0 idle, no pod babysitting. |
| **Mac-local cockpit** | One surface; runs the whole pipeline on free data. |
| **Calibration + sizing + sanity layers** | The discipline/honesty layer — the genuine differentiator. |
| **Telegram signals, entry/exit engine, chosen-stop** | Solid, usable execution plumbing. |
| **Finding the truth** | We *know* what doesn't work. Most never find out. |

## What failed

| | |
|---|---|
| **Kronos as alpha** | Doesn't beat naive baselines anywhere meaningful. |
| **OpenAlice dependency** | Fragile; dropped for free Yahoo data. |
| **Oracle box worker** | Path mismatch → silently stale; bypassed. |
| **Idle pod billing** | Burned ~$10 before serverless fixed it. |
| **Classic factors** | Momentum weak (t=1.74); low-vol inverted by regime. |
| **Price-only anomalies** | Overnight-drift absent; vol-squeeze rejected. |
| **Silent git push failures** | Hidden by `tail`; the box never updated. |

## Key numbers (the evidence)

- Baseline study n≈1,800: Kronos beat naive in **1 of ~36 cells** (`forex@30` expectancy).
- Momentum IC on S&P 500 (36 cuts): **+0.051, t=1.74** (not significant).
- Low-vol IC: **−0.078, t=−2.21** (significantly inverted this regime).
- Vol-squeeze forward-move ratio: **0.93** (squeezes → *smaller* moves).

## Next ideas (priority order)

1. **Regime awareness** *(next build)* — FRED/ALFRED point-in-time macro →
   growth×inflation quadrant + yield-curve + risk-on/off; condition every signal.
   Now the highest-value piece, since standalone signals are weak.
2. **Event/flow/positioning signals** — short-squeeze setups (FINRA short interest),
   PEAD on under-covered names, **CFTC COT** extreme-positioning reversals, EDGAR 13F.
   *This is where outsized moves actually come from.*
3. **Kronos removal** — once the new core carries the pipeline, surgically remove
   `kronos_service/`, `serverless/`, `kronos_client`, `kronos_features`,
   `forecast_calibration`, and the forecast bits of `run`/`report`/`scoring`/`sanity`/UI.
4. **Walk-forward replay + winner-autopsy** — run the full live stack at a past date,
   grade picks, analyse what real winners shared (hypothesis-gen → confirm in IC harness).
5. **Global breadth (MSCI World)** — cheap now (factors need no GPU).
6. **Daily-choices cockpit view** + paper-trade → realized-performance loop.

## Biggest difficulties (honest)

1. **No edge found yet.** The central unsolved problem. Classic edges are
   arbitraged thin; the model adds nothing; price patterns are efficient.
2. **The real edges need harder data.** Outsized moves live in events/flows/
   positioning — which means new data pipelines (short interest, earnings,
   COT, 13F), not just price.
3. **Signal vs noise discipline.** Everything interesting is small-sample (FX,
   regime-conditioned buckets). The constant risk is data-mining a backtest into
   false confidence. We hold the line: hypothesis-first, confirm out-of-sample.
4. **Strategy articulation.** We have *ideas* and infrastructure, but not yet a
   concrete, confirmed strategy. Turning "volatility-age, outsized-moves" instinct
   into a tested, executable edge is the work ahead.
5. **Keeping identity coherent through pivots.** OpenAlice → Kronos → factors;
   each pivot risked losing the thread. Now tracked in ROADMAP.md + memory.

---

## Current architecture (how it runs)

- **Cockpit:** `Vigil.command` → `scanner.server` (FastAPI), runs the pipeline
  locally on free Yahoo data, offline (no OpenAlice). `VIGIL_WORKER_URL` commented
  out so it doesn't route to the stale box.
- **Forecasting (being retired):** serverless GPU via `KRONOS_SERVERLESS_ENDPOINT`
  + `RUNPOD_API_KEY`.
- **Research (no GPU):** `python -m scanner.factor_backtest`, `scanner.anomaly_study`,
  `scanner.backtest` (the last still uses Kronos/serverless).
- **Secrets:** `.env` only (gitignored). Public repo: `github.com/tiagorf1/Vigil`.

See `ROADMAP.md` for the live backlog and `CLAUDE.md` for build context.
