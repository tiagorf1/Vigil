# Vigil — Full Feature List

Everything the system does today, grouped by area. Items marked **(live-verified)**
have been exercised end-to-end on this machine; the rest are built and unit-tested
but await a live OpenAlice server for full-path confirmation.

---

## 1. Pipeline & orchestration
- **Six-stage pipeline**: universe → portfolio/macro context → screen → batched
  forecast → holdings review → reports. (`scanner/run.py`)
- **Multiple invocation modes**: natural-language directive (`"European banks"`),
  explicit ticker list (`"AAPL MSFT NVDA"`), broad sweep (`""`), `--from-file`.
- **Graceful degradation**: every external call (OpenAlice, Kronos, LLM) catches,
  logs, and returns empty/None — one bad symbol never aborts a scan.
- **Hard abort conditions only**: OpenAlice unreachable, LLM key missing for the
  chosen provider, or Kronos service fails to start — each with a clean message
  (no stack traces). **(live-verified)**
- **Per-run overrides**: `--provider`, `--max-results`, `--asset-class`, `--no-ui`.

## 2. Universe building (`scanner/universe.py`)
- Directive parsing → asset-class inference (equity vs crypto vs index).
- Explicit-symbol detection (`AAPL,MSFT` or `AAPL MSFT`).
- OpenAlice `marketSearchForResearch` discovery for themes/sectors.
- Search-result validation via Yahoo quote type, dropping obvious non-tradeable
  product/category results before screening.
- Curated seed universe (40 equities + 8 crypto) for empty/broad directives.
- Dedupe + cap at `MAX_UNIVERSE_SIZE`.

## 3. Screening (`scanner/screener.py` + `scanner/indicators.py`)
- **Fundamental screen (equity)**: revenue growth, net income, P/E, analyst
  consensus, insider net buying, debt/equity, earnings beat — scored 0–100.
- **Fundamental screen (crypto)**: 7-day / 30-day momentum + volume spike.
- **Technical screen**: RSI(14), MACD(12,26,9), SMA(50/200), ATR(14),
  Bollinger(20,2) — scored 0–100.
- **Local indicators**: all technicals computed in pandas from a single OHLCV
  fetch per symbol (no `calculateIndicator` round-trips). **(live-verified math)**
- **Concurrent screening** with a semaphore (8 in flight).
- **Lenient fallback**: if <3 names clear both thresholds, rank all by combined
  score so the watchlist is never empty (logged).
- Cap survivors at `MAX_SCREENED_SIZE`.

## 4. Forecasting — Kronos (`kronos_service/`, `scanner/kronos_client.py`)
- **Warm model service**: FastAPI wrapper loads Kronos once and stays resident;
  auto-starts as a subprocess if not running. **(live-verified)**
- **Device auto-detect**: CUDA / Apple `mps` / CPU. **(live-verified on mps)**
- **Batched inference** (`predict_batch`): all survivors in one GPU pass, chunked
  for memory. **(live-verified)**
- **Probabilistic forecasts** — Monte-Carlo path cloud (`KRONOS_MC_PATHS`):
  - `prob_up` — probability of a positive return at the horizon.
  - `ret_q05 / q50 / q95` — 5th / 50th / 95th percentile return (90% range).
  - `terminal_vol`, `step_vol` — forward volatility.
  - `cone` — per-step quantile bands for the fan chart.
  **(live-verified: 24 paths in ~12s on mps)**
- Point fields retained: `expected_return_pct`, `forecast_high/low`,
  `path_spread_pct`, mean-path candles.
- Health endpoint reports model + device; short-history symbols skipped cleanly.

## 5. Synthesis — research reports (`scanner/report_generator.py`)
- **Pluggable LLM provider**: `gemini` (free, default) | `anthropic` | `none`.
- **Structured output**: Gemini `response_schema` guarantees the JSON shape;
  template fallback needs no key. **(none-path live-verified)**
- **Retry/backoff** on rate limits / transient errors (free-tier 429 safe).
- **Exact research schema**: conviction (1–5), thesis, fundamental/technical/
  forecast summaries, entry/stop/target, risk-reward, timeframe, strategy type,
  risks, tags.
- **Richer decision support**: 2–3 paragraph thesis, 4–6 concrete `reasons`,
  and a `horizon` bucket (`low` / `medium` / `high`) for short-term vs longer
  fundamental setups.
- **Decision shapers**: output carries the factor values that shaped the idea
  (scores, Kronos return/probability/range, RSI, MACD, ATR, SMA distance,
  drawdown) for direct UI display.
- **Probabilistic context** fed to the model (P↑, quantiles, vol).
- **Vol-sized stops**: risk levels derived from Kronos forward volatility, falling
  back to ATR then a fixed estimate; labelled by basis.
- Strategy-type inference (momentum / mean_reversion / breakout / value).

## 6. Portfolio awareness (`scanner/openalice_client.get_positions`)
- Reads current OpenAlice positions.
- **Held tagging** on watchlist names you already own.
- **Holdings review**: forecasts held names not otherwise screened.
- **Exit signals**: held names with a negative forecast surfaced as a distinct
  list (UI + markdown).

## 7. Macro & events
- **Macro backdrop** via FRED/BLS (`economyFredSearch`): 10y yield (DGS10), dollar
  index (DTWEXBGS), CPI (CPIAUCSL) — shown as a header ticker.
- **Earnings-window tagging**: equities reporting inside the forecast horizon are
  tagged `earnings_in_window` (`equityGetEarningsCalendar`).

## 8. Calibration (`scanner/calibrate.py`)
- Self-scores past `outputs/*.json` forecasts against realized prices.
- Metrics: **hit-rate** (direction), **MAE** of return, **Brier** (probability
  calibration).
- Writes `outputs/calibration.json`; hit-rate displays in the UI header.
- Runs standalone: `python -m scanner.calibrate`.

## 9. OpenAlice integration (`scanner/openalice_client.py`)
- **Dynamic tool resolution**: lists the live MCP catalog and matches intents to
  real tool names (survives renames). **(live tool surface inspected)**
- **Daily disk cache** (`scanner/cache.py`) for profiles/financials/ratios/
  earnings — fast re-runs and scheduled scans.
- **Inbox push** (`--push-inbox`): sends the watchlist to OpenAlice's Inbox (MCP
  tool with HTTP `/api/events/ingest` fallback).
- **Order staging** (`--stage-orders`): stages — never executes — limit orders for
  conviction-4+ picks for human approval in OpenAlice.

## 10. Output (`scanner/output.py`)
- Ranked watchlist JSON (conviction desc, then expected return).
- **Sector-diversification cap** (max 3 per sector, relaxed only if short).
- Per-name payload: scores, probability fields, cone, forecast candles, held flag,
  sector, horizon, `reasons`, performance metrics, full report.
- `outputs/latest.json` pointer for the UI; timestamped history files.
- Markdown export with macro line, exit-signals section, and per-name detail.

## 11. Web UI (`ui/index.html`)
- **Vigil — FT-styled design**: salmon "FT pink" paper, Source Serif headlines,
  Hanken Grotesk data, claret/teal accents, conventional green/red P&L, hairline
  column rules. **(live-verified via screenshot)**
- **Section-index nav**: one-click market scans — World indexes / US / Europe /
  Asia / Crypto.
- **Control panel** (when run via the app server): directive input, asset-class
  toggle, provider select, options (push-inbox / stage-orders / max-results),
  and a RUN button — no terminal needed.
- **Live 6-stage progress stepper** during a scan.
- **Scan history** selector to reload any past watchlist.
- **Watchlist**: rank, conviction stars, strategy badge, expected return, P↑,
  HELD badge, R/R, horizon badge, and horizon filter chips.
- **Exit-signals** alert strip.
- **Report**: thesis, "Why now" reasons, performance metrics,
  fundamentals/technicals/forecast columns, **fan chart** with the 5–95% Kronos
  cone, probability + 90% range line, strategy levels (vol-based stop labelled),
  risks, tags.
- **Macro ticker** + **calibration hit-rate** in the header.
- Works statically too (reads `outputs/latest.json`) with a graceful no-API mode.
- **(UI render live-verified via screenshot)**

## 12. Ways to run
- **Browser control panel** (recommended, no terminal): `python -m scanner.server`
  then use the RUN button. **(this build)**
- **Double-click launcher**: `Vigil.command` starts the server and opens the
  browser. **(this build)**
- **CLI**: `python -m scanner.run "<directive>" [flags]`.
- **Scheduled**: hook `scanner.run`/`scanner.calibrate` into cron or the
  `schedule` lib (Phase 3 scaffolding present).

## 13. Configuration (`.env`, `scanner/config.py`)
- Providers/keys, OpenAlice URL, Kronos model/tokenizer/device/paths, MC path
  count, lookback/horizon, universe/screen/watchlist caps, UI port.
- Single frozen `Config` with validation and abort-condition checks.

## 15. Index component scans (`scanner/universe.py`, `scanner/index_components.py`)
- **Tradeable ETF benchmarks**: S&P 500 -> `SPY`, Nasdaq 100 -> `QQQ`, Dow 30
  -> `DIA`. ETF forecasts are stored as benchmark context, not watchlist ideas.
- **Sector sleeve benchmarks** on broad US/S&P scans: `XLK`, `XLF`, `XLV`,
  `XLE`, `XLY`, `XLP`, `XLI`, `XLB`, `XLU`, `XLRE`, `XLC`.
- **Component expansion**: index directives expand into company tickers (S&P 500,
  Nasdaq 100, Dow 30), then companies are screened/reported as equities.
- Triggered from the UI nav, `--asset-class index`, or "index/indices" keywords.
- Current local path caps components with `MAX_INDEX_COMPONENTS_LOCAL` and caps
  expensive forecasting/reporting with `MAX_SCREENED_SIZE`; full every-component
  forecasts belong on remote workers.

## 16. Telegram signals (`scanner/notify.py`)
- Sends a concise HTML message to your phone after a scan when a pick clears
  `SIGNAL_MIN_CONVICTION` / `SIGNAL_MIN_RETURN`, or on any exit signal.
- Stays quiet when nothing qualifies; `--notify` forces, `--no-notify` mutes.
- `SIGNAL_MARKETS` controls the scheduled scan loop (`world,us,europe,asia,crypto`
  and/or `portfolio`).
- Free, iPhone-friendly. **(message builder live-verified; send needs your token)**

## 17. Free data fallback & 24/7 (`scanner/market_data.py`, `.github/workflows/`)
- **Yahoo Finance OHLCV fallback** (no API key) when OpenAlice has no price
  history — and `--offline` mode runs the whole pipeline with no OpenAlice at all.
  **(live-verified: indexes/crypto/equities)**
- **GitHub Actions daily cron** (`vigil-signals.yml`): runs a world-index scan in
  the cloud and pushes Telegram signals — free, no always-on machine.

## 14. Testing & quality
- **22 unit tests** (screener, indicators, cache, kronos client incl. batch,
  output incl. sector cap) + a gated live integration test. **(all passing)**
- Tolerant parsers throughout (unknown response shapes score 0, never crash).
- Error-handling contract enforced at every external boundary.
