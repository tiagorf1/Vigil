# Vigil — Refined Plan v2 (2026-06)

*Premise: a small retail account, EU-based, long-biased equities plus FX/CFD
access. Options are off limits as an instrument. WRDS access exists now but
expires with the MSc, which makes it a research-window asset, not
infrastructure. Goal: build the system right once, then run a research loop
that improves it without external review.*

---

## Part 0 — The constraints, stated once

Everything below is filtered through these. Write them into
`CONSTRAINTS.md` and check every hypothesis against them before coding:

- **Instruments:** long equities (US + European), FX and possibly commodity
  exposure via CFDs (costly — financing eats slow signals). No options. No
  practical single-name shorting. Short *signals* are still usable as
  exclusion filters on the long book.
- **Capital:** small. This is an *advantage* in exactly one dimension —
  capacity. A small account can hold positions in small/micro-caps and
  under-covered names where institutional money physically cannot operate.
  Every signal choice below exploits this. Hunting edge in mega-caps with a
  small account is competing where you're weakest for prizes that were
  arbitraged away anyway.
- **Data:** WRDS (CRSP with delisting returns, point-in-time Compustat,
  IBES, OptionMetrics, short interest) until graduation; free sources after
  (EDGAR, FINRA, Yahoo/Finnhub/Alpha Vantage, CFTC). Two consequences:
  - **Lab/production split:** all historical validation runs on WRDS data
    *now*, while it exists. The live pipeline is built only on sources that
    survive graduation. Never promote a signal whose live inputs you'll lose.
  - **License honesty:** academic WRDS terms generally restrict commercial
    use. Using it to validate research methodology is the gray-but-standard
    zone; piping it into a live trading system is not. The lab/production
    split keeps you on the right side of this anyway.
- **Tax/cadence:** Portugal taxes gains at 28%, and high-frequency activity
  risks worse treatment. Target turnover: monthly-to-quarterly rebalance plus
  event-driven entries. No signal with weekly turnover survives costs + tax
  at this account size.

---

## Part 1 — Build it right (one-time, sequenced)

### Phase 0 — Hygiene (this week, unchanged from v1)

Rotate the worker token and purge `worker_token.rtf` from history; fix the
README; excise Kronos completely in one sprint (keep the calibration and
sizing libraries — they're signal-agnostic and they're the good part).
Create `CONSTRAINTS.md` and `HYPOTHESES.md`.

### Phase 1 — The lab, rebuilt on WRDS (2–4 weeks, the clock is ticking)

This is where WRDS access is worth the most, so it goes first:

1. **Universe layer:** CRSP point-in-time membership with delisting returns.
   Define two test universes: (a) US small/mid-cap ex-microcap-illiquid
   (price > $5, some ADV floor you can actually trade), (b) European
   equivalent if data allows. The S&P 500 becomes a *control* universe — if
   a signal works there too, fine, but it's not where you're hunting.
2. **Fundamentals/estimates layer:** point-in-time Compustat and IBES with
   correct lagging (fundamentals known with delay; never join on fiscal
   period end dates).
3. **Cost model:** spread proxy by market-cap/ADV bucket + commission +
   slippage haircut. Every number the harness prints is gross *and* net.
   Small caps are the hunting ground precisely because costs are higher
   there — the lab must price that honestly or it will flatter everything.
4. **Statistics:** Newey–West for overlapping horizons; log the count of
   hypotheses tested; FDR haircut on anything reported as a finding;
   deflated Sharpe for strategy-level results.
5. **Vault:** the most recent 18 months of data are untouchable until a
   signal has passed everything else. One look per signal, ever.
6. **The lab gate (promotion policy, written into the repo):**
   pre-registered → economically motivated → significant after the FDR
   haircut → positive *net* of costs → survives the vault → live inputs
   available from free sources → executable under `CONSTRAINTS.md`.

### Phase 2 — Candidate signals, prioritized for this operator

All long-side or long-filter. Each gets a `HYPOTHESES.md` entry with
mechanism, predicted sign, universe, horizon, and pass/fail threshold
*before* testing. Roughly in order of (documented survival × retail fit ×
data durability):

1. **PEAD on under-covered small caps.** Standardized unexpected earnings
   (SUE) from IBES; drift is strongest exactly where you can trade and
   institutions can't: low analyst coverage, small size, high
   limits-to-arbitrage. Validate on WRDS/IBES; production inputs are an
   earnings calendar plus reported-vs-estimate data from free APIs. This is
   the flagship candidate: event-driven (fits Vigil's "surface something
   actionable" identity), long-side, capacity-constrained.
2. **Analyst revisions momentum.** Upgrades and estimate-revision breadth
   predict continuation, again strongest in smaller names. IBES for
   validation; free estimate data is thinner in production, so this may
   end up as a *component* of a composite rather than standalone — the lab
   will say.
3. **Insider buying (opportunistic, not routine).** EDGAR Form 4 is free
   forever, which makes this the most *durable* pipeline in the whole plan.
   The documented refinement: separate opportunistic insiders from routine
   calendar-pattern traders (Cohen–Malloy–Pomorski); clustered opportunistic
   buying in small caps is one of the better-surviving signals. Long-only by
   nature. Build the EDGAR parser early — it's also reusable plumbing.
4. **Residual (idiosyncratic) momentum.** Momentum on factor-model residuals
   rather than raw returns: documented to survive better post-publication,
   less crowded, lower crash risk than raw 12-1. Replaces the tired classic
   momentum you already tested. Validate on CRSP; production needs only
   prices, which you have for free.
5. **Short interest as an exclusion filter.** High short interest predicts
   underperformance; you can't short, but you can refuse to be long what
   informed shorts are leaning on. Validate on WRDS short interest;
   production from FINRA's free bimonthly file. Cheap, durable, and it
   compounds with everything above.
6. **Quality/profitability tilt as ballast.** Gross profitability
   (Novy-Marx) in small caps, long-only. Not exciting alone; valuable as the
   stabilizing leg of a composite and as a junk filter on the event signals.
7. **Option-implied ranking of stocks** *(signal, not instrument)*. IV skew
   and implied-vol spread sorts predict equity returns; you'd buy the stock,
   never the option. Validate on OptionMetrics while you have it. The honest
   production problem: free live IV data is mediocre, so this either earns a
   free-data pipeline (delayed CBOE/yfinance chains, liquid names only) or
   gets archived as validated-but-dormant. One subsection of the lab, not
   the center of the project.
8. **FX/commodity trend with your expectancy structure.** Your `forex@30`
   expectancy cell is the CTA literature in miniature: trend profits come
   from payoff asymmetry (cut losers, ride winners), not direction skill.
   You already independently rediscovered this — formalize it. Test
   time-series momentum with the chosen-stop engine, net of *realistic CFD
   financing*, which is the thing most likely to kill it. If it survives
   net, it's the diversifying sleeve that doesn't correlate with the equity
   book.
9. **COT positioning extremes** as a conditioning input on sleeve #8 only.
   Free CFTC data, documented but weak standalone.

Explicitly demoted, with reasons on record: raw price/vol pattern mining
(the lab already ruled), 13F cloning (stale and crowded), short-squeeze
trades (no short execution), index-rebalance front-running (arbitraged),
and per-signal regime conditioning (overfitting machine at these sample
sizes — regimes return in Phase 4 as exposure scaling only).

### Phase 3 — Portfolio construction (where small accounts actually win or lose)

Individual signal ICs will be small. The realistic engineering:

1. **Composite scoring.** Combine 3–5 weak, *lowly-correlated* signals
   (event drift + insider + revisions + quality + short-interest exclusion)
   into one cross-sectional rank. Diversification across signals raises the
   composite's information content the same way diversification across
   stocks lowers variance — this is where the actual edge of the system
   lives, not in any single anomaly.
2. **Book shape:** long-only, 15–30 names, position caps, sector caps,
   liquidity floor sized to the account. Equal-ish weights — at this account
   size, optimization sophistication is noise.
3. **Turnover budget:** a hard cap (e.g., signals may only replace N names
   per month outside of events). Costs and Portuguese tax make turnover the
   silent killer; budget it like risk.
4. **The discipline layer you already built** — vol-target sizing,
   fractional Kelly, chosen-stop, Telegram — wraps all of it. This is the
   part of Vigil that was always good; it finally gets real signals to
   discipline.

### Phase 4 — Regimes, the modest version (later)

One dumb, pre-registered regime indicator (yield-curve slope plus a trailing
risk-on/off measure, point-in-time via ALFRED) doing exactly one thing:
scaling gross exposure between roughly 0.5× and 1.0×. No sign flips, no
per-signal conditioning. Evaluate on drawdown reduction, not returns.

---

## Part 2 — Improve it alone (the self-correcting loop)

The request was a system you can correct without waiting on anyone. That's a
process design problem, and the process is the product:

1. **Pre-registration as law.** No test without a dated `HYPOTHESES.md`
   entry first. Failed entries never get deleted. Six months from now, the
   ratio of registered-to-reported is your own audit trail against
   self-deception — the failure mode that solo researchers have no colleague
   to catch.
2. **Kill criteria defined at promotion, not in the moment.** When a signal
   passes the gate, its demotion condition is written in the same commit
   (e.g., "rolling 12-month net IC below zero for two consecutive quarters →
   demote to watch"). You will not be a neutral judge of your own signal
   while it's bleeding; pre-commit so the judging is already done.
3. **The forward ledger from day one.** Paper-trade the composite the moment
   it exists. Every pick logged with its signal attribution at entry. Forward
   results are the only data with zero look-ahead by construction, and they
   accumulate while you do everything else.
4. **Monthly autopsy ritual (fixed calendar slot, ~2 hours).** Grade the
   ledger; for the biggest winners and losers, record what the signals said
   at entry and what actually drove the move. Patterns spotted here become
   new `HYPOTHESES.md` entries — autopsy generates hypotheses, the lab
   confirms them, never the reverse. This is your replacement for a research
   team.
5. **Annual revalidation.** Every promoted signal gets re-run once a year on
   the data that has accrued since promotion. Edges decay (you've read
   McLean–Pontiff); schedule the check rather than trusting yourself to
   remember.
6. **One-in-one-out attention budget.** Solo operators die from breadth. Cap
   live research at two open hypotheses at a time; a new idea enters the
   queue, not the workbench.
7. **WRDS sunset task.** A standing checklist item until graduation: for
   every promoted signal, confirm its production inputs are free-source and
   already flowing. The day access ends, nothing in the live system should
   notice.

---

## Sequencing summary

| Window | Work |
|---|---|
| This week | Token/README/Kronos removal; CONSTRAINTS.md; HYPOTHESES.md |
| Weeks 1–4 | Lab rebuild on WRDS: universes, costs, stats, vault, gate |
| Weeks 3–8 | Signals 1–5 through the lab (PEAD, revisions, insiders, residual momentum, short-interest filter); EDGAR parser built in parallel |
| Weeks 6–10 | Composite + portfolio construction; forward ledger goes live |
| Weeks 8–12 | FX trend sleeve net of CFD costs; quality ballast; option-implied study while WRDS lasts |
| Quarterly+ | Regime exposure-scaling layer; autopsy → hypothesis → lab loop runs indefinitely |

## The one-paragraph version

Hunt only where a small account has structural advantage: under-covered
small caps and event-driven drift, long-side, low turnover. Use WRDS now as
a research window — clean validation on CRSP/Compustat/IBES with costs and
multiple-testing control — while building the live system exclusively on
data that outlives your enrollment. Expect no single signal to be a star;
the edge is a composite of four or five weak, uncorrelated, documented
tilts, executed through the discipline layer you already built, at a
turnover the costs and the Portuguese tax code can survive. Then run the
loop that lets you correct yourself: pre-register, pre-commit kill criteria,
keep a forward ledger, autopsy monthly, revalidate annually, and never have
more than two hypotheses open at once.
