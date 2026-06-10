# Vigil Handoff — Session Brief

Date: 2026-06-10  
Latest pushed commit: `d4d524b Add daily board and evidence scores`  
Repo: `https://github.com/tiagorf1/Vigil`  
Local path: `/Users/tiagoferreira/Scanner Project`

This handoff is intentionally narrow. It covers the work from this session and
what the next Codex session should do next.

---

## 1. User Goal This Session

The user wanted Vigil to become more believable without becoming overprocessed.
Core themes:

- Fund/tech scores felt fake because too many names clustered at values like
  `100` or `40`.
- The UI should rank opportunities by risk profile, not act as a hard selector.
- Counter-trend trades should not be killed automatically; they may be the best
  asymmetric ideas.
- Scheduled scans should not overwrite each other. If US, Europe, crypto, FX,
  commodities run as separate buckets, earlier buckets must survive in one board.
- Accumulation must be daily only. Tomorrow starts fresh.
- Prepare the system for more asset types and later options work, but do not
  blow up the overnight scan before it can run.

High-level answer: we made scores more honest and made bucket scans accumulate
into a same-day combined board.

---

## 2. What Was Built

### A. Daily Board Aggregator

New file:
- `scanner/daily_board.py`

Behavior:
- Every scheduled bucket still writes its normal timestamped watchlist.
- `scanner.signals` now calls `daily_board.ingest(path, spec.label)` after each
  bucket finishes.
- The bucket result is copied into:
  - `outputs/daily/YYYY-MM-DD/<bucket>.json`
- A combined board is rebuilt at:
  - `outputs/daily/YYYY-MM-DD/combined.json`
- `outputs/latest.json` is rewritten from today’s combined board.

Important design choice:
- Buckets are overwritten by bucket name, not appended. Re-running “US bucket”
  replaces today’s US bucket instead of duplicating stale ideas.
- Tomorrow uses a different folder, so yesterday cannot leak into tomorrow.

Why this matters:
- Before this, each bucket scan overwrote `outputs/latest.json`.
- Now `global-liquid` can finish in stages, and the UI sees the combined day board.
- US results will not hide Europe/FX/crypto/commodities.

### B. Evidence Scores For Fund/Tech

New file:
- `scanner/evidence_scores.py`

Wired in:
- `scanner/run.py`
- `scanner/output.py`
- `ui/index.html`

Behavior:
- After screening and data-quality cleanup, survivors get evidence-normalized
  scores.
- Raw scores are preserved as:
  - `raw_fund_score`
  - `raw_tech_score`
- Displayed scores become:
  - raw score blended with same-scan peer percentile
  - plus data confidence
  - gently pulled toward neutral when evidence is thin

Why this matters:
- A raw `100/100` no longer displays as fake certainty.
- A `40/100` no longer means “bad” in isolation; the UI can show whether it was
  weak vs today’s peers or just a coarse bucket.
- This keeps the user’s “ranker, not selector” philosophy intact.

### C. UI Updates

Changed:
- `ui/index.html`

Visible effects:
- Watchlist rows show `source_bucket` when loaded from a combined daily board.
- “Fund screen” / “Tech screen” language is now “Fund evidence” / “Tech evidence.”
- Data tab includes “Evidence score calibration”:
  - evidence score
  - raw score
  - peer percentile
  - data confidence
- Header pill shows combined board status, e.g. `combined 4 buckets`.

### D. Tests

New tests:
- `tests/test_daily_board.py`
- `tests/test_evidence_scores.py`

Verification run:

```bash
PYTHONPATH=. python3 -m pytest -q
```

Result:

```text
105 passed, 1 skipped, 1 warning
```

The warning is an existing pandas runtime warning in a screener test, not caused
by this session.

---

## 3. Files Changed

New:
- `scanner/daily_board.py`
- `scanner/evidence_scores.py`
- `tests/test_daily_board.py`
- `tests/test_evidence_scores.py`

Modified:
- `scanner/run.py`
- `scanner/signals.py`
- `scanner/output.py`
- `ui/index.html`
- `HANDOFF.md`

Untracked and intentionally untouched:
- `worker_token.rtf`

---

## 4. Deployment State

Commit was pushed to `origin/main`:

```bash
git push origin main
```

Cloud deploy commands for Oracle:

```bash
cd ~/Vigil
git pull
source .venv/bin/activate
sudo systemctl restart vigil-worker
```

If delaying the scheduled midnight scan and running manually:

```bash
sudo systemctl stop vigil-signals.timer
cd ~/Vigil
source .venv/bin/activate
python -m scanner.signals global-liquid
sudo systemctl start vigil-signals.timer
```

Check timers:

```bash
systemctl list-timers 'vigil-*'
```

Check worker logs:

```bash
journalctl -u vigil-worker -f
```

If `python` fails on Oracle, use the venv and `python`, or system `python3` only
after dependencies are installed. The known good pattern is:

```bash
cd ~/Vigil
source .venv/bin/activate
python -m scanner.signals global-liquid
```

---

## 5. Current Automation / Buckets

Known `SIGNAL_MARKETS` profile from the code:

`global-liquid` runs four buckets:

1. Global liquid index ETFs:
   - `SPY QQQ DIA IWM EWU FEZ EWG EWQ EWP EWI EWJ MCHI FXI EWY EWT INDA`
2. Liquid commodity ETFs:
   - `GLD SLV USO UNG CPER PPLT PALL DBA CORN WEAT`
3. Top FX pairs:
   - `EURUSD=X GBPUSD=X USDJPY=X USDCHF=X USDCAD=X AUDUSD=X NZDUSD=X EURJPY=X GBPJPY=X EURGBP=X`
4. Crypto majors:
   - `BTCUSD ETHUSD SOLUSD BNBUSD XRPUSD ADAUSD AVAXUSD DOTUSD LINKUSD DOGEUSD`

New behavior:
- Each bucket lands separately under today’s folder.
- The UI/latest result becomes the combined daily board.
- Tomorrow starts as a new folder automatically.

---

## 6. Rationale

### Why not penalize counter-trend trades?

Because the user is right: counter-trend can be where the gold is. The system
should identify the condition, not bury it. Counter-trend is now better treated
as a trust/profile signal:

- conservative profile: usually dislikes it
- aggressive/speculative profiles: may like it if levels and payoff are good

### Why evidence scores instead of “real truth” fund/tech scores?

A single 0-100 score is dangerous if it pretends to be truth. The better move is:

- keep the raw score
- show where it ranks against peers scanned today
- show confidence in the underlying data
- avoid hard filtering unless the data is truly broken

This answers the user’s concern about “killing it in the crib.” Thin data should
reduce confidence, not delete ideas.

### Why same-day accumulation?

The scan runs in buckets because a single giant scan is slow and fragile. But a
bucketed runner must not make the latest bucket look like the whole market.

The daily board gives both:

- bucket-level completion
- one combined board for the day

And because it is date-scoped, there is no stale accumulation into tomorrow.

---

## 7. What Is Still Weak

Most important weaknesses:

1. Forecast magnitudes are still too large.
   - Expected-return shrinkage exists conceptually, but the real backtest still
     needs to be run on the cloud box to produce trustworthy sample-backed
     calibration.

2. Fund/tech evidence scoring is survivor-only.
   - It currently reshapes scores among cleaned survivors, not across the full
     candidate universe.
   - Better next step: compute evidence percentiles across all candidates before
     final survivor selection.

3. Technical score is still indicator-bucket based.
   - It should become a continuous setup score:
     trend, momentum, reversal, volatility compression, relative strength,
     drawdown, distance from key averages, and volume confirmation.

4. Fundamental score is better than before, but not yet sector-native enough.
   - It needs sector-relative valuation/profitability/growth/liquidity.
   - Banks, insurers, REITs, commodity producers, and software companies should
     not be judged by the same generic formula.

5. Daily combined board ranking may need bucket caps.
   - The combiner dedupes and reranks, but it does not yet enforce “max N per
     bucket” by default.
   - If one bucket floods the board, add a config setting or call `ingest(...,
     max_per_bucket=N)`.

6. Cloud backtest/calibration is not done yet.
   - This is still the biggest trust upgrade.

---

## 8. Recommended Next Session Plan

Priority order:

1. Run/deploy this commit on Oracle and confirm `global-liquid` produces:
   - `outputs/daily/YYYY-MM-DD/*.json`
   - `outputs/daily/YYYY-MM-DD/combined.json`
   - combined `outputs/latest.json`

2. Run real backtest on Oracle:

   ```bash
   cd ~/Vigil
   source .venv/bin/activate
   python -m scanner.backtest --horizons 10 30 60 --cuts 8 --lookback 180 --paths 12
   ```

   If too slow:

   ```bash
   python -m scanner.backtest --symbols AAPL MSFT SPY QQQ GLD BTCUSD ETHUSD EURUSD=X --horizons 10 30 --cuts 4 --lookback 180 --paths 8
   ```

3. Add true expected-return shrinkage from backtest R² / realized error.
   - Goal: Kronos headline returns stop screaming `+15%` unless the model has
     earned that magnitude historically.

4. Upgrade fund/tech scoring properly:
   - sector-relative fundamental percentiles
   - continuous technical setup scores
   - factor-level explanations
   - confidence shown separately from opportunity

5. Add bucket caps / board sections if today’s combined board becomes dominated
   by one bucket.

6. Then resume options work.
   - Options should use the same philosophy: expected payoff, liquidity hygiene,
     IV vs forecast vol, spread/slippage, and sizing, not “buy calls because
     bullish.”

---

## 9. Source Direction For Better Scores

Use these as the source backbone for the next fund/tech scoring pass:

- CFA Institute, Financial Analysis Techniques:
  https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/financial-analysis-techniques
  - Use for ratios, liquidity, solvency, profitability, activity, DuPont logic,
    and the warning that ratios must be interpreted in context.

- CFA Institute, Integration of Financial Statement Analysis Techniques:
  https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/integration-financial-statement-analysis-techniques
  - Use for comparability, accounting choices, quality of data, and sector/context
    dependence.

- CFA Institute, Introduction to Financial Statement Analysis:
  https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/introduction-financial-statement-analysis
  - Use for the full statement-analysis framework and why notes, filings, and
    management commentary matter.

- Fama and French, A Five-Factor Asset Pricing Model:
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2287202
  - Use for factor direction: value, profitability, and investment behavior have
    evidence in average returns.

- Kenneth French Data Library, Fama/French 5 Factors:
  https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library/f-f_5_factors_2x3.html
  - Use for factor definitions and eventual factor benchmarking.

- Jegadeesh and Titman, Returns to Buying Winners and Selling Losers:
  https://www.bauer.uh.edu/rsusmel/phd/jegadeesh-titman93.pdf
  - Use for cross-sectional momentum evidence.

- Brock, Lakonishok, and LeBaron, Simple Technical Trading Rules:
  https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1992.tb04681.x
  - Use cautiously for moving-average/trading-rule evidence. Account for costs
    and out-of-sample fragility.

- Lo, Mamaysky, and Wang, Foundations of Technical Analysis:
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=228099
  - Use for the idea that technical patterns should be algorithmic and statistically
    tested, not visually hand-waved.

Working principle:
- Fundamentals should score economic quality, valuation, growth, balance-sheet
  strength, revisions, and sector context.
- Technicals should score setup quality, not “chart vibes.”
- Backtests decide weights. Human logic proposes features; realized results earn
  the right to move ranking/sizing.

---

## 10. Mental Model For The Next Agent

The user is not asking for a conservative filter. They want a ranker that can
surface aggressive, asymmetric opportunities without pretending certainty.

Do:
- preserve raw values
- show confidence separately
- rank by profile
- treat counter-trend as information
- let backtests earn trust
- keep the UI honest about what is measured vs inferred

Do not:
- bury new ideas just because the ledger is young
- let one bucket overwrite the rest
- call a score “truth”
- hard-penalize reversals without checking payoff/levels
- add complexity that cannot affect tomorrow’s scan

The best next win is still believability:
real cloud backtest → sample-backed calibration → expected-return shrinkage →
cleaner fund/tech factor scores.
