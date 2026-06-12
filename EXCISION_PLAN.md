# Kronos excision — execution blueprint

*Mapped from a dry run (then reverted to keep `main` green). Follow this to
remove the forecast layer cleanly in one focused sprint. Keep the calibration
*methodology* and the sizing/TA engines — they are signal-agnostic and reused.*

## 1. Delete outright (infra + pure-forecast modules)
```
git rm -rf kronos_service serverless
git rm -f scanner/kronos_client.py scanner/kronos_features.py \
  scanner/forecast_calibration.py scanner/intraday.py scanner/horizon.py \
  scanner/calibrate.py scanner/meta_model.py scanner/strategy_backtest.py \
  scanner/backtest.py scanner/options.py
git rm -f tests/test_kronos_client.py tests/test_meta_model.py \
  tests/test_strategy_backtest.py tests/test_calibration_prob.py \
  tests/test_integration.py tests/test_options.py
```
- `options.py` goes too: it's forecast-dependent vol analysis AND options are
  off-table per CONSTRAINTS.
- Remove the `kronos_*`, `serverless`, `forecast_calibration` fields/props from
  `config.py` (and `KRONOS_*`/`RUNPOD_*` lines from `.env`).

## 2. De-thread the 3 live importers
Only three live files import deleted modules (verified): `run.py`, `signals.py`,
`options.py` (deleted). `track_record.py` is already clean.

### `scanner/run.py` — the real work (~150 lines)
- **Remove imports:** line ~24 `from scanner.kronos_client import ...`; in-loop
  `from scanner import forecast_calibration`, `horizon as HZ`, `kronos_features`,
  `meta_model`, `options`.
- **Replace the `[4/6]` forecast stage** (~L224–310: ensure_service, two-stage
  `forecast_batch`, benchmark + held forecasts) with a no-op:
  `horizons = cfg.horizon_list; forecasts_by_h = {}; forecasts = {}; benchmark_forecasts = []; exits = []`
  (drop the held-name forecasting; exits come later from the ledger, not forecasts).
- **Rewrite `build_entry`** forecast-free:
  - `per_h = {}`, `fc = None`, `side = "long"` (long-only per CONSTRAINTS;
    short signals are exclusion filters, never positions).
  - `ta = entry_exit.analyze(cand.ohlcv, direction="long")` — keep all TA/levels/stop logic (L355–376, 437–452) verbatim; it's signal-agnostic.
  - Replace `sel = HZ.select(...)` with a synthetic dict:
    `sel = {"horizon_days": max(horizons), "horizon_class": "swing", "agrees": ta.get("trend") == "up", "confidence": None, "term_structure": None}`.
  - **Delete** the `kronos_features` (L453–468), `meta_model` (L469–481), and
    `options` (L494–503+) blocks entirely.
  - Ranking key becomes the **screen/evidence score** (fund+tech), not forecast
    edge — until a lab signal is promoted to replace it.
- Sizing: `sizing.from_pick` currently reads `_barrier`/`prob_up`; make it fall
  back to vol-target-only sizing when those are absent (it largely already does).

### `scanner/signals.py`
- Remove `from scanner.kronos_client import KronosClient` and the
  `kronos.forecast_batch` call in the bucket scan; mirror run.py's no-op stage.

## 3. Keep (signal-agnostic — the good part)
`entry_exit.py`, `sizing.py`, `indicators.py`, `factors.py`, `factor_backtest.py`,
`anomaly_study.py`, `screener.py`, `universe.py`, `market_data.py`, `yahoo.py`,
`output.py` (drop forecast/cone fields), `report_generator.py` (drop
forecast_summary; it already tolerates `fc={}`), `scoring.py` (drop barrier/
expected_r branch → score from fund/tech/TA), `sanity.py` (drop forecast audits).

## 4. Acceptance
- `PYTHONPATH=. pytest -q` green (after fixing `test_sizing`/`test_scoring`/
  `test_track_record` to not assert forecast fields).
- `python -c "import scanner.run, scanner.signals, scanner.server"` clean.
- Cockpit scan produces a **long-only, screen+TA+vol-sized watchlist** (thin,
  no alpha ranking) — expected until the lab promotes a signal.

## 5. After excision → Phase 1 (the lab on WRDS)
Per REFINED_PLAN_v2: point-in-time universe, cost model in every output,
Newey–West + FDR, the 18-month vault, the written lab gate. Then H-001 (PEAD).
