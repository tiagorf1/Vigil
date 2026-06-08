# Vigil — Limitations Audit (what stops it being a tool that *works*)

Honest inventory, grouped. "Works" = sends signals you can trust enough to act on.

## 1. Signal quality (the core blocker)
- **Kronos directional edge is unproven / weak.** Held-out backtest: ~coin-flip
  direction, slightly NEGATIVE rank correlation at 20d, 0-50% cone coverage.
  Until a walk-forward test shows edge, the forecast is a *confirmer*, not a caller.
- **Single fixed horizon.** Forecast length is a config number (90d), not chosen
  per opportunity. Longer = less certain. Horizon should be an OUTPUT.
- **Kronos and TA are loosely coupled.** Kronos gives a direction/prob; TA
  (support/resistance, ADX, SMA/EMA, Bollinger) gives levels/setup — but the
  entry/exit decision doesn't yet REQUIRE them to agree at the right horizon.
- **Calibration is in-sample.** Bias/cone fixes are fit on the same data; not yet
  walk-forward cross-validated.
- **Meta-model has no data yet.** It needs matured paper trades to learn.

## 2. Data
- **Fundamentals are snapshot-only (Yahoo).** No historical statements -> no real
  growth trend, no Piotroski, no sector-relative valuation. (EDGAR/FMP fix this.)
- **OpenAlice fundamentals never worked:** undocumented response shapes (field
  guesses missed -> puppet score), only works when its dev server is up (not
  offline/cloud), depends on its own upstream providers.
- **Daily bars only.** No intraday -> cannot do true day-trade entries/exits.
- **News / earnings dates fetched but not scored** into the signal.
- **No fundamentals for crypto/FX/commodity** (they have none intrinsically).
- **No data-quality guardrails** (splits, illiquid, stale, currency).

## 3. Validation / trust
- No walk-forward CV; no strategy equity-curve (does following signals make money
  net of costs?); paper ledger just started (no matured outcomes).

## 4. Execution / ops
- 90d x many paths is slow + hot on the Mac. Cloud worker built but not deployed.
- No position sizing (how much). No regime filter (works in some markets only).
- Telegram thresholds are arbitrary (conviction>=4), not edge-derived.
- Entry/exit levels aren't monitored after the scan (no "stop hit" alert).

## 5. Product completeness
- TA (`_ta`) + meta-prob computed but not surfaced in the UI.
- No "why" explainability shown; no alerting on level breaches.

---

## Target architecture (the vision, made concrete)
TECHNICAL is the spine; KRONOS confirms; FUNDAMENTALS rank quality; the SYSTEM
picks the horizon.

1. **TA defines the setup + levels** (deterministic, reliable): trend (SMA/EMA),
   momentum (RSI/MACD), volatility (Bollinger/ATR), structure (swing S/R), ADX.
   This produces entry zone, stop, target, R:R, confluence.
2. **Kronos confirms at the matching horizon**: forecast at {10,30,60}d; the
   opportunity CLASS = the shortest horizon where the (calibrated) forecast is
   confident AND agrees with the TA setup. Short+confident -> "low/short-term";
   only-long-agrees + strong fundamentals -> "high/long-term". Horizon is OUTPUT.
3. **Fundamentals rank quality** (equities) and gate longs (don't hold a
   deteriorating company long-term).
4. **A trade only fires when TA + Kronos agree**; size by vol; alert on level hit.

## Fundamentals sources, ranked for "free + ideally no key"
- **SEC EDGAR companyfacts** (data.sec.gov) - FREE, NO KEY, official filings,
  full history. US-only; needs ticker->CIK map (SEC provides free). BEST no-key
  high-quality source. Fits as another provider in `fundamentals.py`.
- **Yahoo quoteSummary** (current) - free, effectively keyless (crumb handled),
  global, but snapshot-only. Good fallback / non-US.
- **FMP** - free *tier* but needs a key; global, history, sector medians. Best if
  a key is acceptable.
- **OpenAlice** - keyless but only when running; would need its real field shapes
  pinned. Use as enrichment when live, not the backbone.
Recommendation: **EDGAR (US, no key) + Yahoo (global fallback)**, both behind the
existing provider switch. FMP optional.
