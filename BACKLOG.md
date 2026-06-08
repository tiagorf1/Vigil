# Vigil — Idea Backlog (don't forget these)

Captured so nothing is lost. Not in priority order within tiers.

## On the burner (discussed, do soon)
- [DONE] **Theory-grounded fundamentals.** `scanner/factor_models.py` encodes
  Piotroski F-score (9-pt, real YoY from Yahoo timeseries), Greenblatt Magic
  Formula (earnings-yield + ROC, snapshot-approx & flagged), and Graham defensive
  checklist. `fundamentals.fetch` pulls the keyless balance-sheet history and
  attaches `_frameworks`; `fundamentals.score` blends 82% buckets + 18% framework
  consensus. Surfaced in the UI (frameworksBlock with per-check ✓/✗). Outcome
  tuning of weights still deferred to the meta-model (item under Validation).
- [DONE] **Options / vol module** (was under "surface the gold"): see below.
- **News / events layer.** For equities: light sentiment (mostly "seen it = missed
  it"). For FX/commodities/crypto: a MACRO EVENT CALENDAR (rate decisions, CPI/NFP,
  inventories) with a proximity flag ("ECB in 2 days -> widen stops / stand aside").
  This is where FX/commodities are actually driven.
- [PARTLY DONE] **Universe definitions.** CRYPTO top-N by mkt cap via free
  CoinGecko (no key) is wired (`universe.coingecko_top`, used for broad/"top N"
  crypto directives, stablecoins/wrapped filtered, majors fallback). FX + commodity
  presets already existed. Still open: surface a one-click crypto-top-N chip in the
  UI nav like the index presets.

## Surface the gold already computed (built but under-used)
- [DONE] Use kronos_features in SCORING: `scanner/scoring.py` composite "Vigil
  score" blends conviction + barrier prob-weighted R + barrier edge + calibrated
  P(up) + Kronos-quality/screens, renormalised over available components, with a
  forecast-disagreement penalty. It is now the primary ranking key (output.py)
  and is shown in the list, header tile, and a "how it's built" breakdown.
- [DONE] Surface `_ta` (setup/ADX/trend/confluence/signals) + `_meta_prob_up` in
  the Report tab (setupBlock); barrier/term/kfeat/kqual already in Data tab.
- [DONE] Wire Yahoo insights (technical S/R + outlook) and peers into the report
  (run.py best-effort fetch -> insightsBlock/peersBlock in Data tab).
- Intraday (1m/5m) bars -> true short-horizon Kronos forecasts for day-trades.
- [DONE] Options: `scanner/options.py` — Kronos-vol vs implied-vol (vol edge +
  cheap/rich call), expected-move comparison, P(>call strike)/P(<put strike) from
  the terminal cone, and a probability-aware option idea. Wired in run.py for
  equities/ETFs; optionsBlock in the Data tab; vol_cheap/vol_rich tags.

## Validation / trust (the thing that makes it "work")
- [DONE] Walk-forward forecast CV: `backtest.py` (out-of-sample hit-rate, bias,
  cone coverage, rank-corr -> forecast_calibration.json).
- [DONE] Strategy equity-curve backtest: `strategy_backtest.py` applies the TA
  entry/stop/target to history intrabar -> win rate, expectancy, profit factor,
  Sharpe, max drawdown, by-setup breakdown, vs buy-hold. Zero Kronos cost.
- Still open: let the paper ledger mature, then train the meta-model; gate "trust"
  on results. (meta_model exists; needs matured labels.)

## Risk / sizing / portfolio
- [DONE] Position sizing: `sizing.py` (fractional Kelly + vol target from barrier
  P(target)/prob_up + TA payoff + forward vol). Shown in the Report tab; $ amounts
  when VIGIL_ACCOUNT_EQUITY is set.
- [DONE] Regime conditioning: `regime.py` (VIX level+trend -> risk-on/off banner +
  tilt + tag). Informs, does not silently rewrite scores.
- [DONE] Data-quality guardrails: `dataquality.py` quarantines insufficient/penny/
  illiquid/split-jump/flat series before forecasting; soft issues -> data_warning.
- Still open: correlation-aware basket + pairs (long A / short correlated B);
  currency-mismatch detection.

## Sector-relative
- [DONE] Valuation vs PEER MEDIAN within the scan (`run.py` peer_median_pe ->
  val_cheap/rich/inline_vs_peers tag + valRelBlock). Absolute-sector medians
  (needs sector reference data) still open.

## Product / ops
- [DONE] Surface _ta (setup, ADX, confluence, signals) + _meta_prob_up in the
  report (setupBlock).
- [DONE] Alert when a live position hits its trailing stop / target
  (signals.portfolio_sell_check now sends Kronos-sell + TA position-level alerts).
- [DONE] Intraday (1m/5m/15m) short-horizon Kronos forecasts: `intraday.py` CLI
  (the last unused Yahoo endpoint, now wired).
- Eventually: native app (long future); browser cockpit is the interim.

## Follow-ups (noted during cloud bring-up)
- DEFAULT_PRED_LEN is still used for SECONDARY forecasts (benchmark ETFs, held/
  exit review) and as the paper-ledger horizon label. Replace these with the
  per-pick operative horizon from horizon.select() (and use max(KRONOS_HORIZONS)
  for benchmarks), so no single global horizon leaks into scoring/labels.
