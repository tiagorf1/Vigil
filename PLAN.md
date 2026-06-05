# Vigil — Plan / Handoff

State as of this session. App is WORKING: `python -m scanner.server`, 22 tests
pass, all modules import. Offline index/crypto scans produce real ideas.

## Done this session
- Local portfolio (portfolio.json): add from watchlist, remove, list. API:
  /api/portfolio[/add|/remove|/check]. UI: "+ Portfolio" btn + "My portfolio" nav.
- Portfolio merged into scans -> HELD tags + Exit (sell) signals; standalone
  `scanner.signals` portfolio sell-check + Telegram.
- Market-choice signals: SIGNAL_MARKETS env + `scanner/signals.py` loops markets
  (+ "portfolio"); workflow uses it.
- Company NAMES + symbol validation: scanner/names.py (index/crypto maps + Yahoo
  search resolver, cached; drops non-tradeable quoteTypes). Wired into run.py for
  survivors.
- More indicators: indicators.py adds ret_1m/3m/6m/1y, ann_vol, 52w hi/lo + dist,
  max_drawdown_1y, dist_sma50/200, avg_vol.
- Longer/richer reports: report_generator system prompt asks for 2-3 para thesis,
  4-6 numbered `reasons`, and `horizon` (low/medium/high). Schema + validation +
  template all updated (template verified: name, 6 reasons, metrics, horizon).
- Trading-horizon buckets: report.horizon (low=day-trade/technical/volatile,
  high=long-term/fundamental). output carries it; UI has horizon filter chips +
  per-row badge + colored kicker.
- output.py carries horizon, reasons, metrics (per-item).
- Remote Kronos: KRONOS_SERVICE_URL -> offload forecasting (client skips local spawn).

## Final implementation pass — COMPLETE and verified
1. End-to-end offline US-index scan completed:
   `python3 -m scanner.run "us" --asset-class index --offline --provider none --no-ui`.
   Wrote `outputs/watchlist_20260605_152007.json` and refreshed
   `outputs/latest.json`.
2. Confirmed `outputs/latest.json` has 4 items and every item includes:
   `name`, `horizon`, 12 `metrics`, and 6 report `reasons`.
3. Added universe-level Yahoo quote-type validation for OpenAlice search results,
   so odd non-tradeable product/category symbols are dropped before screening.
   Also fixed the explicit-symbol heuristic so prose like "quality software" is
   not mistaken for ticker input.
4. Added unit coverage for the universe validation path.
5. Updated FEATURES.md, TUTORIAL.md, and README.md for horizon/reasons/metrics,
   local portfolio, signal markets, and remote Kronos.
6. Fixed `.env.example` and `.env` `KRONOS_SERVICE_URL` comments, and hardened
   config parsing so comment-only env values are treated as blank.
7. UI QA complete through the app server: report renders Why now, Performance,
   horizon badges/filter, portfolio button, and `synth: none` from watchlist
   metadata. No browser console errors.
8. Final tests: `python3 -m pytest tests/ -v` -> 24 passed, 1 integration skipped.

## Open design answers the user asked for (write up when usage returns)
- "Fully using both repos?" NO, by design. Kronos: using forecasting + batch +
  MC paths; NOT using its finetuning or qlib backtester (see NEXT_IDEAS #1).
  OpenAlice: using market-data MCP tools, positions, FRED macro, earnings, inbox,
  stagePlaceOrder; NOT its agent/workspace/execution loop (we deliberately only
  consume it as a data+staging source). Many OpenAlice tools (analyst estimates,
  calculateIndicator) we replaced/located dynamically.
- "Offload CPU / make it an app?" Three honest options, simplest first:
  (a) 24-7 signals already run in GitHub Actions cloud (free, off your machine).
  (b) KRONOS_SERVICE_URL points at a remote Kronos box (one env line; DONE).
  (c) "Actual app": the browser control panel already IS app-like; a thin
      Tauri/Electron wrapper or a PWA is possible but not necessary — more effort
      than value right now. Recommendation: (a)+(b), skip native packaging.
- Fastest path to first live test = the offline index scan (no OpenAlice). See
  STARTUP.md §1.

## Key files
scanner/: run.py (orchestrator), server.py (API+UI), signals.py (cron),
  portfolio.py, names.py, indicators.py, screener.py, report_generator.py,
  output.py, notify.py, market_data.py (Yahoo fallback), kronos_client.py,
  calibrate.py, universe.py (INDEX_PRESETS), config.py.
kronos_service/: predictor.py (batch+MC), main.py (/forecast,/forecast_batch).
ui/index.html (FT/Vigil single-file app). .github/workflows/vigil-signals.yml.
Vigil.command launcher. Docs: STARTUP.md, TUTORIAL.md, FEATURES.md, NEXT_IDEAS.md.
