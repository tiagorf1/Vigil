# VIGIL — Project Handoff (read this first in a fresh session)

Vigil is a personal investment-opportunity scanner. Pipeline:
**universe → screen → Kronos forecast → LLM synthesis → ranked watchlist**, viewed
in a browser cockpit, with a 24/7 cloud watcher that pushes Telegram signals.
Internal package name is `scanner`; product name is **Vigil**.

Owner: tiagorferreira1@gmail.com · GitHub: https://github.com/tiagorf1/Vigil

---

## 1. Architecture (where things run)

- **Mac cockpit** (`/Users/tiagoferreira/Scanner Project`): the browser UI + control
  panel (`scanner.server`, port 8080). It does NOT compute — it **forwards scans to
  the cloud worker** (because `VIGIL_WORKER_URL` is set in `.env`).
- **Oracle cloud box** (Ubuntu ARM, 4 OCPU/24 GB, always-on): runs the heavy work.
  - IP `51.170.32.169`, user `ubuntu`, SSH key `~/.ssh/vigil-oracle` (has a passphrase).
  - `vigil-worker` systemd service = job API on port `8090` (token-auth via `X-Vigil-Token`).
  - Kronos forecasting service (started by the worker) on port `8765`, **Kronos-base on CPU**.
- **Kronos** (`~/Kronos`): the OHLCV forecasting model. `kronos_service/` wraps it in FastAPI.
- **Data**: Yahoo Finance (free, keyless via crumb) for OHLCV + fundamentals. **OpenAlice is
  GONE** (deleted; `openalice_client` is an offline stub).
- **LLM**: Gemini (`gemini-2.5-flash`) for report synthesis + the Layer-2 critic.

Flow of a cockpit scan: browser → `POST /api/scan` (Mac) → `_run_remote_job` forwards to
cloud `POST /jobs` (offline=true) → worker runs `scanner.run.run_scan` → saves
`outputs/latest.json` on the box → Mac polls + downloads it (and `/api/watchlist?file=latest`
also pulls the cloud's latest on open, so results survive the Mac being closed).

---

## 2. Cloud ops (how to update / run)

SSH in: `ssh -i ~/.ssh/vigil-oracle ubuntu@51.170.32.169`

Update the box (ONLY when no scan is running — restarting kills an in-flight job):
```bash
cd ~/Vigil && git pull && sudo systemctl restart vigil-worker
```
Services & timers:
- `vigil-worker.service` — job API (always on).
- `vigil-bot.service` — interactive Telegram command bot (needs Telegram tokens).
- `vigil-signals.timer` — **00:00 London** pre-market sweep → runs `SIGNAL_MARKETS`.
- `vigil-portfolio.timer` — midday + afternoon portfolio guard.
Enable: `sudo systemctl enable --now vigil-signals.timer vigil-portfolio.timer`
Check: `systemctl list-timers 'vigil-*'` · logs: `journalctl -u vigil-worker -f`
Health from Mac: `curl -s http://51.170.32.169:8090/health` → `{"status":"ok",...}`

Firewall gotchas (already handled by `deploy/setup-oracle.sh`): Oracle needs BOTH a cloud
Security-List ingress rule for tcp/8090 AND the box's local iptables opened (Oracle Ubuntu
rejects non-22 by default → "No route to host").

`deploy/setup-oracle.sh` is the one-shot provisioner (ARM-aware torch, clones repo+Kronos,
venv, .env, systemd units, firewall, auto-generates `VIGIL_WORKER_TOKEN`).

---

## 3. Config (`.env`; template `.env.example`)

Key vars: `LLM_PROVIDER=gemini`, `GEMINI_API_KEY`, `KRONOS_MODEL=NeoQuasar/Kronos-base`,
`KRONOS_DEVICE=cpu` (cloud), `KRONOS_MC_PATHS=24`, `KRONOS_SCREEN_PATHS=6` (2-stage),
`KRONOS_HORIZONS=10,30,60` (auto-selected), `DEFAULT_PRED_LEN=60` (fallback only),
`KRONOS_HTTP_TIMEOUT=3600` (base on CPU is slow), `VIGIL_WORKER_URL`/`VIGIL_WORKER_TOKEN`
(Mac→cloud), `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`, `SIGNAL_MARKETS`,
`VIGIL_ACCOUNT_EQUITY` (0 = weights only), `SIZING_KELLY_FRACTION=0.5`, `SIZING_TARGET_VOL=0.15`,
`VIGIL_START_OPENALICE=false`.

**SIGNAL_MARKETS** = comma list the watcher walks in order. Tokens:
`portfolio` (your holdings → sell alerts), `europe`/`us`/`world` (index level),
`global-liquid` (ETF + FX + commodity + crypto baskets), `crypto`, `forex`, `commodities`,
or any named index (`ftse 100`, `dax`, `euro stoxx 50`). Recommended:
`SIGNAL_MARKETS=europe,crypto,forex,us` (EU indices first, US stocks last; portfolio has
its own timer).

---

## 4. Module / function log (`scanner/`)

- **config.py** — `Config` dataclass + `get_config()` (lru-cached). All env access here.
- **run.py** — CLI + pipeline. `run_scan(args)` orchestrates; `build_entry(cand)` builds one
  pick (picks side from forecast, TA levels, horizon select, barrier, kronos features, meta,
  insights/peers, options); `preflight()`; 2-stage forecasting; single-asset full-tilt.
- **server.py** — FastAPI cockpit. `/api/scan`, `/api/watchlist`, `/api/health`,
  `/api/outputs`, `/api/calibrate`, `/api/portfolio/*`. `_run_remote_job` (forward to cloud),
  `_pull_cloud_latest` (persistence). Serves `ui/index.html`.
- **worker.py** — remote job API. `POST /jobs`, `GET /jobs/{id}`, `/jobs/{id}/result`,
  `/result/latest`, `/health`, `_auth` (token).
- **universe.py** — `UniverseBuilder.build`; `NAMED_INDEX` + `_match_named_index`
  (FTSE/DAX/Euro Stoxx/Nikkei/etc.); `coingecko_top` (crypto top-N, keyless); seed lists.
- **screener.py** — `Screener.screen`; `Candidate` (fund_score, tech_score,
  **tech_short_score**, combined/short_combined/**best_combined**); `_score_technical`
  (bullish + bearish), `_score_fundamental_equity/_momentum`.
- **indicators.py** — RSI/MACD/SMA/ATR/BBands; `compute_all`, `ohlcv_to_frame`.
- **fundamentals.py** — `fetch` (Yahoo quoteSummary crumb + optional FMP); `score`
  (8-bucket methodology + 18% framework blend); `_enrich_frameworks`.
- **factor_models.py** — `piotroski`, `greenblatt`, `graham`, `evaluate` (0-100 framework score).
- **entry_exit.py** — `analyze(ohlcv, direction)` → LONG **or** SHORT levels (stop/entry/
  target, RR, confluence, setup, trend, trail_stop); `_adx`, `_swings`.
- **horizon.py** — `select(forecasts_by_h, ta, horizons)` → operative horizon (shortest
  confident + forecast-agrees-with-trend), horizon_class, term_structure.
- **kronos_client.py** — `KronosClient.forecast_batch/forecast/ensure_service_running`.
- **kronos_features.py** — `barrier_probabilities` (P(target/stop first), **expected_r** =
  prob-weighted R-multiple, NOT a probability), `vol_edge`, `kronos_quality`.
- **forecast_calibration.py** — `apply(fc, asset_class, horizon)` de-bias + widen cone +
  **de-pin prob_up** (clamp [0.02,0.98]); `_DEFAULT_CALIBRATION` (shipped, add_pct=0).
- **scoring.py** — `composite(report, forecast, fund, tech)` → Vigil score, **direction- and
  horizon-aware** (shorts use 1-prob_up; fundamentals weighted by horizon).
- **sizing.py** — `kelly_fraction`, `suggest`, `from_pick`; binding ∈ {no_edge, kelly,
  vol_target, **max_position**}.
- **sanity.py** — `audit(report, forecast)` → Layer-1 deterministic invariant violations.
- **report_generator.py** — `ReportGenerator.generate` (LLM report, long/short framed);
  `critique` (**Layer-2 LLM critic** of computed numbers); `_call_llm/_call_gemini` (schema-opt).
- **options.py** — `analyze` (Kronos vol vs implied, P(>strike), vol-play idea).
- **yahoo.py** — `intraday`, `fundamentals_timeseries` (keyless), `options_chain`,
  `insights`, `recommendations`.
- **output.py** — `WatchlistOutput.build/save/to_markdown`; ranks by Vigil score; attaches
  sizing + runs the sanity audit per pick.
- **regime.py** — `classify`/`detect` (VIX risk-on/off banner).
- **dataquality.py** — `analyze` (quarantine insufficient/penny/illiquid/split/flat).
- **portfolio.py** — `PortfolioStore` (add/remove/list/performance); your paper book.
- **signals.py** — `run_signals`, `portfolio_sell_check` (the watcher; Telegram).
- **notify.py** — `TelegramNotifier`. **names.py** — symbol → name/validity.
- **market_data.py** — `fallback_ohlcv` (Yahoo chart). **index_components.py** — US index
  expansion. **meta_model.py** — `predict_proba` (untrained logistic). **paper.py** — ledger.
- **calibrate.py** — self-score matured picks. **backtest.py** — walk-forward forecast CV →
  `forecast_calibration.json`. **strategy_backtest.py** — TA equity-curve backtest.
- **intraday.py** — intraday short-horizon Kronos. **telegram_bot.py** — command bot.
- **cache.py** — `DiskCache`. **openalice_client.py** — offline stub (OpenAlice removed).
- **kronos_service/predictor.py** — `KronosForecaster` (`forecast_batch`, `_summarise`
  → cone, quantiles, features); **main.py** — `/forecast`, `/forecast_batch`, `/health`.

Run modes: cockpit `python -m scanner.server` (or `Vigil.command`) · CLI
`python -m scanner.run "AAPL MSFT" --offline` · watcher `python -m scanner.signals europe`
· backtest `python -m scanner.backtest` · strategy backtest `python -m scanner.strategy_backtest AAPL`
· intraday `python -m scanner.intraday AAPL --interval 5m`. Tests: `pytest -q` (84 pass).

---

## 5. How a pick is built (the believability chain)

1. Universe → screen (fund + tech, **both long & short merit**) → top survivors.
2. 2-stage Kronos: cheap sweep (6 paths) → refine top buffer (24 paths) at 10/30/60d.
3. `forecast_calibration.apply`: widen cone to real error stdev, **de-pin prob_up**.
4. `entry_exit.analyze`: side chosen from the forecast → LONG/SHORT structural levels.
5. `horizon.select`: operative horizon (shortest confident + agrees with trend).
6. `kronos_features.barrier_probabilities`: P(target before stop), expected_r, on YOUR levels.
7. LLM report (`generate`, long/short framed) + `meta_model` prob.
8. `scoring.composite`: direction/horizon-aware Vigil score; counter-trend −30%.
9. `sizing.from_pick`: fractional-Kelly capped by vol target / max-position.
10. `sanity.audit` (Layer 1) + `critique` (Layer 2) check coherence; flags shown in UI.

---

## 6. CHANGE-LOG (this build cycle)

- Model → **Kronos-base** (largest public; large=499M is unreleased).
- **Composite Vigil score** as the ranking key; surfaced TA setup, meta prob, Yahoo
  insights/peers, Kronos features/quality, barrier, term-structure, frameworks, sizing.
- **Theory fundamentals** (Piotroski/Greenblatt/Graham) blended into the fundamental score.
- **Options/vol module**; **regime** (VIX); **data-quality guardrails**.
- **Backtests**: walk-forward forecast CV + TA strategy equity-curve.
- **Longs AND shorts**: direction chosen from forecast; first-class short sourcing in the
  screener; short LLM framing; direction+horizon-aware scoring.
- **Two safety nets**: Layer-1 deterministic invariants (`sanity.py`) + Layer-2 LLM critic.
- **Believability**: prob_up de-pinned + clamped; cone widened via shipped calibration;
  uniform mean de-bias (add_pct) disabled (was inflating bullish forecasts).
- **Cloud**: Oracle worker + persistence (`/result/latest` + auto-pull); configurable
  `KRONOS_HTTP_TIMEOUT` (3600); pre-market sweep + portfolio-guard timers (London tz).
- **UI redesign** (Fraunces/Hanken/JetBrains Mono, minimal); removed obsolete controls +
  dead "Send to Alice"; Europe/named-index awareness + nav chips; auto-refresh; tag fixes.
- Critic-found bug fixes: prob_up 0/100, sizing `max_position` binding, counter-trend
  mislabel (→ mean_reversion), `prob_R`→`expected_r` rename.

---

## 7. KNOWN ISSUES / believability caveats (work most needed here)

1. **Forecast magnitudes still large & prob_up still high.** Kronos overstates directional
   magnitude; e.g. +15-20% medium-horizon moves, prob_up ~89-98%. Mitigated (de-pin, wider
   cone, add_pct=0) but NOT solved. **Next:** shrink expected return toward 0/drift
   (regularization), and run `scanner.backtest` on the box to get a real, sample-backed
   `forecast_calibration.json` (re-enables trustworthy bias correction).
2. **3 separate horizon forecasts** (10/30/60) = inconsistent paths + 3× the compute. **Next:**
   run ONE 60-step forecast and slice it to 10/30/60 (consistent + ~3× faster).
3. **Base-on-CPU is slow** (~30-40 min for a single full-tilt name; index sweeps hours).
   Timeout raised to 3600. **Next:** GPU box, or the slicing win, or fewer paths.
4. **Counter-trend trades are common** (Kronos vs price trend) — handled (mean_reversion
   label + −30% penalty + tag), but watch that they don't dominate the watchlist.
5. **European = index level only** (no European single-stock constituents).
6. **No free-text theme search** (OpenAlice gone). Only tickers / known index names work.
7. **meta_model untrained** — needs the paper ledger to mature.

---

## 8. WHAT'S NEXT (prioritized)

1. **Believability:** expected-return shrinkage + run a real backtest for calibration.
2. **Efficiency:** single-forecast multi-horizon slicing.
3. **Free-text theme search** (must NOT preempt the portfolio guard).
4. **Train the meta-model** once the ledger has matured picks; gate "trust" on backtest.
5. First-class European single-stock universes (constituent lists).
6. GPU option for Kronos-base (fast interactive scans).

---

## 9. SAFETY / secrets

- Secrets live ONLY in `.env` (gitignored): `GEMINI_API_KEY`, `TELEGRAM_*`,
  `VIGIL_WORKER_TOKEN`. Never commit them. The repo is **public** on GitHub — keep it clean.
- Vigil is advisory: it never executes trades. `--stage-orders` only STAGES for human review.
- A second agent ("Codex") sometimes edits in parallel — `git pull --rebase` before pushing.
