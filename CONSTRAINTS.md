# CONSTRAINTS.md

*The operator's reality. Every hypothesis in `HYPOTHESES.md` is checked against
this before any code is written. An edge the operator cannot execute is not an
edge. Update this when reality changes; date the changes.*

Last updated: 2026-06-12

## Instruments
- **Equities — two execution venues:**
  - **T212 Invest** (real fractional shares, ~0% commission, FX fee ~0.15%):
    the home for *slow* signals (monthly+ holds) — **no overnight financing**.
  - **T212 CFD** (5–10× leverage, **long AND short**): the home for *faster or
    stronger* signals and for leverage. Carries **overnight financing** (~ESTR/SOFR
    + ~3% annual on position value), which eats slow signals — so CFD is for
    higher-conviction, shorter-hold, or leveraged positions, not slow tilts.
- **Shorting IS available** (CFD), so short signals can be *positions*, not just
  exclusion filters — but every short pays financing, so it must clear that bar net.
- **Leverage is wanted** a good part of the time (CFD). The lab must therefore
  report results both unlevered and with the financing cost of leverage/shorts.
- **FX / commodities via CFD** — diversifying sleeve; same financing caveat.
- **No options as an instrument** (signal-only; revisit if a viable broker appears).
- **Brokerage is flexible** — currently T212; will switch for better fees/coverage.
  Hard exclusions: **IBKR** (not usable here) and **tastytrade** (withdrawal cost
  kills it). Any replacement must be available in Portugal/EU.

## Capital
- **Small account.** The one structural advantage this buys is **capacity**:
  the account can hold small/micro-caps and under-covered names where
  institutional capital physically cannot operate. Hunt there. Competing in
  mega-caps is fighting where the account is weakest for prizes already arbitraged.
- Optimisation sophistication is noise at this size — equal-ish weights, hard caps.

## Data (lab/production split — the core discipline)
- **Lab (now, while enrolled):** WRDS — CRSP w/ delisting returns, point-in-time
  Compustat, IBES, OptionMetrics, short interest. Used **only to validate**.
- **Production (must outlive graduation):** EDGAR (Form 4, filings), FINRA
  (short interest), CFTC (COT), free price/estimate APIs (Yahoo/Finnhub/Alpha
  Vantage), self-recorded option chains. **Never promote a signal whose live
  inputs disappear at graduation.**
- **License honesty:** academic WRDS terms restrict commercial use. Validating
  methodology = standard gray zone; piping WRDS into a live trading system = no.
  The lab/production split keeps us clean by construction.

## Tax / cadence (Portugal)
- Gains taxed at **28%**; frequent short-term activity risks worse treatment.
- **Target turnover: monthly-to-quarterly rebalance + event-driven entries.**
  No weekly-turnover signal survives costs + tax at this size. Budget turnover
  like risk (hard cap on monthly name replacements outside events).

## Jurisdiction
- **EU retail → PRIIPs/KID** blocks most US-domiciled ETFs. Prefer single names
  or UCITS wrappers; check tradability before relying on any ETF in production.

## TO CONFIRM (operator must fill — these change the hypothesis space)
- [ ] **Broker(s)** Trading212
- [ ] **Account size band** 500€ up to 5x or 10x margin on CFD account
- [ ] **WRDS graduation / access-end date** May 10, 2028 (reported on page)
- [ ] **Hours/week** 10.
- [ ] **Any** options execution at all (even index), or strictly signal-only? maybe in the future but not until the right brokerage is found
- [ ] Existing positions / starting book to respect.Clean book, nothing
