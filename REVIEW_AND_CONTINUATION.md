# Vigil — Change Review, Conclusions & Continuation
(Review of work that landed since the FT/Vigil session; a second agent "Codex"
+ the user extended the repo. This file records what changed, concludes, and
scopes the next steps.)

## A. Changes noticed (recorded)
New modules / files:
- `scanner/worker.py` — remote scan worker (POST /jobs, GET /jobs/{id}[/result]);
  run on a remote CPU/GPU box, point `KRONOS_SERVICE_URL` / worker at it.
- `scanner/index_components.py` — expands index/ETF aliases (SPY, ^GSPC...) into
  their COMPONENT companies so the equity screener works on real names, not the
  index itself. Weekly-cached.
- `Vigil Full Stack.command` — one launcher that starts OpenAlice + (optionally
  warm) Kronos + Vigil together.
- Docs: `AGENTS.md` (Codex context), `PROCESSING_ROUTES.md` (free/cheap compute
  routing: local app, remote Kronos, spot-GPU for full-index deep scans),
  `GITHUB_ACTIONS_SETUP.md`.
New asset classes: `etf`, `commodity`, `forex` added alongside equity/index/crypto.
  - `screener._score_fundamental_momentum` now covers crypto/index/etf/commodity/forex.
- `scanner/names.py` — `MARKET_NAMES` map for commodity (=F) + FX (=X) futures;
  quote_type now returns FUTURE/CURRENCY; validation extended.
- `scanner/signals.py` — `RunSpec` + `_SIGNAL_PROFILES` (`global-liquid`, `global`):
  baskets of liquid index ETFs, commodity ETFs, top-10 FX, top crypto majors;
  `SIGNAL_MARKETS=global-liquid` runs them all for Telegram.
- `.env` changes: `DEFAULT_PRED_LEN=90` (was 20), `KRONOS_MC_PATHS=24`,
  `MAX_UNIVERSE_SIZE=700`, `MAX_INDEX_COMPONENTS_LOCAL=120`, `VIGIL_WORKER_PORT`,
  `OPENALICE_DIR`, `VIGIL_START_OPENALICE`, `VIGIL_WARM_KRONOS`,
  `VIGIL_REFRESH_ON_OPEN`. Telegram token + chat id now set. `SIGNAL_MARKETS=global-liquid`.

## B. Changes made THIS pass (surgical, to avoid clobbering active work)
1. Gemini API key rotated in `.env` (stored locally, never committed).
2. **95% confidence interval** on forecasts:
   - `kronos_service/predictor.py`: cone + terminal-return percentiles changed
     5/95 -> 2.5/97.5 (now a true 95% CI). Field names q05/q95 kept = lower/upper.
   - `ui/index.html`: "90% range" -> "95% range"; cone caption -> "95% Kronos cone (CI)".

## C. Conclusions
- The stack is now genuinely multi-asset (equity / index->components / ETF /
  commodity / FX / crypto) with free Yahoo data and a remote-compute story. Good
  architecture; the heavy lifting (where to run Kronos) is solved by worker.py +
  KRONOS_SERVICE_URL + PROCESSING_ROUTES.md.
- BUT two correctness/quality gaps remain, both flagged by the user:

### C1. Fundamentals are a "puppet score" (cosmetic) — TRUE
- Equity fundamental screen reads OpenAlice fields; OFFLINE (the default fast
  path) they are empty -> score 0 or momentum free-pass. Index/ETF/commodity/FX/
  crypto all use momentum only. So fundamentals currently add little real signal.

### C2. prob_up reads 100% for many names (e.g. ~10 crypto at 100% up) — UNREALISTIC
- Likely causes, in order:
  (a) `DEFAULT_PRED_LEN=90` — a 90-day horizon over a trending asset makes nearly
      all Monte-Carlo paths end same-sign -> prob pinned at 0/100.
  (b) MC path dispersion too tight (cloud doesn't fan out) -> check
      `terminal_vol_pct`; if small vs |expected_return|, paths are over-clustered.
  (c) Kronos trend-extrapolates; raw prob is uncalibrated.

## D. Continuation (do next, in priority order)

### D1. Make prob_up realistic (highest priority, smallest change)
1. Widen sampling: expose `KRONOS_T` (temperature) + `KRONOS_TOP_P` in config and
   raise defaults (e.g. T=1.1-1.3, top_p=0.95) in `predictor.predict_batch`.
   Re-check that 10 crypto names no longer all read 100%.
2. Horizon sanity: prob over 90d is structurally extreme. Report prob_up at a
   short sub-horizon (e.g. 20d slice of the same paths) AND label the 90d one.
3. Probability calibration: use `calibrate.py` to fit raw prob_up -> realized
   hit-rate (isotonic/Platt) once matured picks exist; display calibrated prob.
4. UI guard: if survivors share an identical extreme prob, show a "low path
   dispersion" warning.

### D2. Real fundamentals (free, no key) — turns the puppet score into signal
1. Equities: add a free Yahoo `quoteSummary` fetch (modules: financialData,
   defaultKeyStatistics, summaryDetail) -> P/E, margins, revenue growth, ROE,
   debt/equity. Wire into `screener._score_fundamental_equity` so it works OFFLINE
   too (mirror `market_data.py` Yahoo pattern; cache via DiskCache).
2. FX: carry = interest-rate differential from FRED (already have get_macro) +
   relative strength vs DXY. Score = carry sign + trend quality.
3. Commodities (oil etc.): term structure (near vs far future = contango/
   backwardation) + USD strength + (optional) news sentiment. Backwardation +
   demand = bullish; contango = bearish.
4. Crypto: no real fundamentals — use momentum + volatility-regime + BTC-dominance
   context, and LEAN on forecast quality (D3), not a fake fundamental number.

### D3. Better predictions where technical is all we have
- Multi-horizon agreement (5/20/60d) -> conviction up only when horizons agree.
- Ensemble: Kronos-small vs Kronos-base; disagreement = uncertainty (lowers prob).
- Trend-quality gate: require structure (ADX / higher-highs) before a "momentum"
  pass counts; filters chop.
- Volatility-regime filter: discount signals when realised vol is in a blow-off
  regime (mean-reversion risk).

### D4. Housekeeping
- `.env.example` line 31/33 have duplicated trailing comments (cosmetic).
- Consider lowering `DEFAULT_PRED_LEN` back to ~20-30 for the default UI scan;
  keep 90 as an explicit "long horizon" option (it strongly affects prob_up).

---

## E. Session: real fundamentals + prob realism + calibration (DONE)
Implemented 1/2/3 from section D (surgically; Codex's files left intact):

1. **Real fundamentals (`scanner/fundamentals.py`)** — free Yahoo quoteSummary
   (crumb/cookie handled), normalized metrics (PE/fwdPE/PEG/PB, margins, ROE,
   rev+earnings growth, D/E, current ratio, FCF, analyst rec + target upside),
   cached daily. `score()` = methodology buckets (valuation/growth/profitability/
   health/analyst) -> 0-100 + breakdown. Live-verified differentiation:
   NVDA 100, PLTR 91, AAPL/KO 83, XOM 69, Ford 51 (neg margin). Works OFFLINE
   and with OpenAlice. This replaces the "puppet" score.
   - `screener._score_fundamental_equity` now uses it (OpenAlice fields kept as
     fallback in `_score_fundamental_equity_openalice`). Candidate gains
     `fundamentals` + `fund_breakdown`; report carries `_fund_breakdown`; the LLM
     payload now receives real fundamentals.
   - WHY it was a puppet even with OpenAlice: scoring keyed on guessed field names
     that never matched OpenAlice's response shape -> every factor missed.

2. **prob_up realism** — diagnosed: MC paths are NOT degenerate (10 distinct
   terminals, vol ~3.8%); the "100% up" came from the **90-day horizon** pinning a
   trending name's direction. Fix: predictor now reports multi-horizon prob from
   the same cloud — `prob_up_1m`, `prob_up_3m`, `prob_up_terminal`, and the
   **headline `prob_up` is now the 1m/3m/terminal blend** (less overconfident),
   plus `exp_ret_1m_pct` / `exp_ret_3m_pct`. 95% CI cone (2.5/97.5) from prior pass.

3. **Calibrate Kronos** — `calibrate.py` now also emits a **reliability curve**
   (predicted vs realized up-rate per probability bucket) and runs **offline**
   (realized closes via Yahoo, no OpenAlice needed). Hit-rate/MAE/Brier already
   there. Becomes meaningful as picks mature; then prob can be recalibrated.

Also: Gemini API key rotated; 28 unit tests pass (added autouse fixture so
screener tests use the offline fundamentals fallback).

## F. Continuation (next)
- Surface `_fund_breakdown` + multi-horizon probs in the UI report (small UI add:
  a "Fundamentals" bar-breakdown block + "1m / 3m / 90d" prob row).
- Consider DEFAULT_PRED_LEN ~30 for the default scan (90 is heavy + makes prob
  extreme); keep 90 as an explicit long-horizon option.
- FX/commodity "fundamentals": carry (FRED rate differential) for FX; futures
  term-structure (contango/backwardation) for commodities — D2.2/D2.3.
- Once calibration.json has matured picks, apply the reliability curve to map raw
  prob_up -> calibrated prob shown in UI.
- Trend-quality / vol-regime gate on the technical score (D3) to cut chop.

---

## G. Backtest + believability verdict (DONE — important)
Built `scanner/backtest.py` (walk-forward evaluator) + `scanner/forecast_calibration.py`
(apply layer, wired into run.py). Exposed `KRONOS_T`/`KRONOS_TOP_P` (top_p 0.9->0.95).

**Held-out finding (are results believable?): NO, raw Kronos-small has no usable
edge here.** Backtest (10 names, H=20, 4 cuts each, n=40):
- equity bias -4.8%, ETF -4.1% (model systematically bearish); crypto +6.2%.
- direction hit-rate ~0.40-0.50 (coin flip); rank correlation slightly NEGATIVE
  on equity/etf/crypto -> the ranking has no predictive edge at 20d.
- model 95%-cone coverage 0.20-0.50 (should be ~0.95): uncertainty was badly
  understated -> this is why prob_up pinned to 0/100.

**Program errors found & corrected:**
1. Uncertainty (cone/prob) was computed from the model's far-too-tight MC cloud.
   Fixed: calibration sets cone width from the *empirical* error stdev and
   recomputes prob_up via a normal approx -> no more fake 0%/100%.
2. Systematic return bias (window mean-reversion + top_p tail truncation).
   Fixed: per-(asset_class,horizon) bias removed; top_p widened to 0.95.
3. The deeper truth calibration CANNOT fix: the model lacks directional skill on
   these names/horizon. Calibration makes the numbers HONEST, not skillful.

**Recommendation:** do not trust direction/conviction for real money yet. Use
Vigil as a screener + honest-uncertainty viewer. To find real edge next:
- walk-forward CROSS-VALIDATION (out-of-sample coverage, not in-sample sigma);
- test shorter horizons (5-10d) and Kronos-base / ensembles;
- lean on what showed signal (fundamentals score; rank within sector);
- only promote a strategy after the backtest shows positive net-of-cost edge.
