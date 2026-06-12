# CONSTRAINTS.md

*The operator's reality. Every hypothesis in `HYPOTHESES.md` is checked against
this before any code is written. An edge the operator cannot execute is not an
edge. Update this when reality changes; date the changes.*

Last updated: 2026-06-12

## Instruments
- **Long equities** — US and European. Primary book.
- **FX / commodities via CFD** — accessible but **financing costs eat slow
  signals**; only fast-or-strong signals survive. Treated as a separate
  diversifying sleeve, not the core.
- **No options as an instrument.** Option-*implied* data may be used as a
  *signal* to rank equities (you buy the stock, never the option).
- **No practical single-name shorting.** Short *signals* are usable only as
  **exclusion filters** on the long book (refuse to be long what informed shorts
  lean on), never as standalone short positions.

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
- [ ] **Broker(s)** and what they actually permit (CFD venue? fractional shares?
      US small-cap access? European small-cap access? borrow availability if any?).
- [ ] **Account size band** (sets the liquidity floor / min position / # names).
- [ ] **WRDS graduation / access-end date** (the lab clock — drives sequencing).
- [ ] **Hours/week** available for the research loop + monthly autopsy.
- [ ] **Any** options execution at all (even index), or strictly signal-only?
- [ ] Existing positions / starting book to respect.
