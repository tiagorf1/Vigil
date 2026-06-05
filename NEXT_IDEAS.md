# Scanner — Next Ideas for Further Improvement

A prioritized backlog beyond the current build. Each item notes the concrete
hook (a repo capability or existing module) so it can be picked up cold.

---

## Tier 1 — highest leverage

### 0. Make the three-repo stack feel like one app
`Vigil Full Stack.command` now starts OpenAlice + warm Kronos + Vigil together.
The next integration step is a small "stack manager" panel in the UI: show
OpenAlice MCP URL, OpenAlice backend URL, Kronos model/device, log links, and
buttons for restart/warm Kronos/recheck health. **Hook:** `scanner.server.health`
already probes OpenAlice and Kronos; extend it with service metadata and a log
tail endpoint.

### 1. Real strategy backtest (not just direction calibration)
We added self-calibration (hit-rate / Brier). The next step is a proper
walk-forward backtest of the *strategy* the scanner emits — entry/stop/target
applied to history — producing an equity curve, Sharpe, max drawdown, and
hit-rate broken out by `strategy_type`. **Hook:** Kronos ships
`examples/run_backtest_kronos.py` and a qlib harness; adapt it to consume the
scanner's signals. This is what turns "conviction" into an earned number.

### 2. Closed-loop screen tuning from calibration
Once `outputs/calibration.json` has enough matured picks, fit a simple model
(logistic regression) of "did this pick work" against the screen factors and
forecast features, and **reweight the scoring** accordingly. The screener stops
being hand-tuned constants and starts learning which factors predict forward
returns on *your* universe. **Hook:** `calibrate.py` already collects the labels.

### 3. Position sizing (fractional Kelly + vol target)
We compute `prob_up`, the q05/q95 payoff, and forward vol — everything needed to
suggest a **size**, not just a direction. Output a fractional-Kelly weight per
name, scaled to a target portfolio volatility, and a suggested dollar amount
given account equity (from OpenAlice's `aggregateAccountFromPositions`). Turns a
watchlist into an allocatable basket.

### 4. Multi-horizon term structure
Forecast at 5 / 20 / 60 days and report the term structure of expected return and
vol. The interesting signal is *divergence*: short-term weak but long-term strong
(accumulate), or the reverse (fade). **Hook:** `predict_batch` already takes
`pred_len`; loop it and add a small horizon selector to the UI.

---

## Tier 2 — new signal & breadth

### 5. Forecast ensemble & disagreement
Run Kronos-small and Kronos-base (and the 2k tokenizer) and measure agreement
across models. High agreement → higher conviction; wide disagreement is itself an
uncertainty signal worth surfacing. **Hook:** both checkpoints exist under the
NeoQuasar HF org; the service can hold two warm models.

### 6. News sentiment as a scored factor
We pass news to the LLM but don't score it. Add a sentiment-momentum factor
(LLM- or model-scored) to the fundamental screen, and flag genuine catalysts vs
noise. **Hook:** `grepNews`/`globNews` already wired in `openalice_client`.

### 7. Cross-asset coverage (commodities & FX)
OpenAlice serves commodities, forex, and macro; Kronos forecasts any OHLCV. Extend
the universe builder + screener to gold/oil/EURUSD-style scans. Mostly a universe
+ asset-class-scoring change; the forecasting path is identical.

### 8. Regime conditioning
Use the macro block (yields, dollar, add VIX) to classify a risk-on/off regime and
shift screen weights — favour momentum/breakout in risk-on, mean-reversion/value
in risk-off. **Hook:** `get_macro` already fetches the series.

### 9. Path-dependent risk metrics
From the per-step cone we can estimate **P(hit stop before target)**, CVaR /
expected shortfall, and max adverse excursion — far richer than a static R/R.
**Hook:** the `cone` arrays are already in every forecast payload.

### 10. Short ideas & pairs
Symmetric treatment for shorts (negative forecast + weak fundamentals), and pair
suggestions (long A / short correlated B) built from a correlation matrix computed
on the OHLCV we already fetch.

---

## Tier 3 — infra, UX, robustness

### 11. Scheduler (Phase 3)
`schedule`-based pre-market daily scan that auto-pushes to the Inbox and persists
history — which also auto-feeds calibration over time. **Hook:** `schedule` is
already a dependency; `--push-inbox` already works.

### 12. Local LLM provider (offline synthesis)
Add `LLM_PROVIDER=ollama` so reports can be generated fully offline. **Hook:**
Ollama is already installed on this machine; the provider abstraction in
`report_generator` makes this a ~30-line addition.

### 13. Incremental / cached forecasts
Cache Kronos outputs keyed by (symbol, last-bar-date); only re-forecast names with
new data. Big speedup for daily scans. **Hook:** mirror the `DiskCache` pattern
already used for fundamentals.

### 14. Conviction explainability
Show the factor-level contributions behind each score (which fundamental /
technical / forecast factors drove it) as a breakdown in the UI — so the user can
trust or challenge a pick.

### 15. Live UI controls
Small SSE-backed scan server: live progress, a re-run button, and editable
parameters (directive, thresholds, horizon) in the browser instead of the CLI.

### 16. Data-quality guardrails
Detect stale/illiquid/penny names, OHLCV gaps and split artifacts, and currency
mismatches; quarantine bad data instead of forecasting on it. Prevents
garbage-in picks.

### 17. Recorded-fixture integration test
Capture a real OpenAlice tool catalog + sample responses once, and replay them so
the integration test runs in CI without a live server. Locks in the tool-name and
response-shape contract the dynamic resolver currently guesses.

---

## Quick wins (an afternoon each)
- "Ask Alice about this pick" deep-dive: after the selected report is pushed to
  Inbox, open or start a focused OpenAlice conversation around that exact packet.
- Log viewer in Vigil for `logs/openalice.log`, `logs/kronos.log`, `logs/vigil.log`.
- Add VIX to the macro strip.
- "What changed since last scan" diff view (new names, conviction moves, drop-offs).
- Cost router: template for low scores, Gemini for mid, Opus for conviction-4+.
- Export watchlist to CSV / push to a Google Sheet.
- `--explain` flag that dumps the raw OpenAlice payloads per symbol for debugging.
