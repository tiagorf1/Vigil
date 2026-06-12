# Vigil — Refined Plan (2026-06)

*An external review of the project log and roadmap: where the judgment was
amateur, what the corrected worldview is, and the plan that follows from it.
Written to be merged into the repo alongside PROJECT_LOG.md and ROADMAP.md.*

---

## Part 1 — Where the judgment was amateur-ish

The log is honest, which puts it ahead of 95% of retail quant projects. But
honesty about *results* coexisted with several methodological and strategic
errors that shaped those results. In rough order of severity:

### 1.1 Product before proof

Act II built a complete product — UI, Telegram, calibration, risk sizing,
109 tests — around a signal that nobody had validated. The backtest harness
that killed Kronos in Act III should have existed in week one; it would have
killed Kronos in week two. This is the classic engineer's failure mode:
building is satisfying and measurable, research is uncomfortable and mostly
produces "no." The cost wasn't just time. Every layer built on top of the
forecast (calibration, the critic, the forecast-aware scoring) now has to be
surgically removed.

**Rule going forward:** no signal touches product code until it has passed
the lab gate (defined in Part 3). Research and product are separate
codepaths with a one-way door between them.

### 1.2 Expecting alpha from a public pretrained model

A model that is published, free, and downloadable cannot contain durable
alpha — if it did, the act of publication starts the clock on its death, and
a price-only transformer is competing against the single most picked-over
data source in finance. Worse, the "honest-forecast layers" (calibration,
sanity, critic) were sophistication applied to a skill-less core: calibration
can make a model's uncertainty honest, but it cannot create skill that isn't
there. You effectively built a beautifully calibrated coin.

Partial credit: you discovered this yourselves, empirically, with a proper
baseline study. Most people never run the baseline.

### 1.3 Testing anomalies in the most efficient universe on Earth

The factor tests ran on the full S&P 500 — current constituents, free Yahoo
data. Three problems compound here:

- **Wrong universe.** Mega-cap US equities are where institutional capital
  has ground every documented anomaly to dust. Momentum at t=1.74 there is
  not evidence that momentum is dead; it's evidence you measured it where it
  was always going to be weakest. The post-publication literature (McLean &
  Pontiff, which you cite) also shows *where* the residual edge survives:
  small caps, low analyst coverage, high limits-to-arbitrage, costly-to-short
  names. Anomalies persist exactly where big money can't profitably chase them
  — which happens to be where a small retail account *can*.
- **Survivorship bias.** Pulling today's S&P 500 list and backtesting it
  means every bankrupt, delisted, or demoted name is invisible. This inflates
  long-side results generally and specifically poisons the low-vol and
  reversal tests. The low-vol "inversion" finding is probably one part
  genuine regime (high-beta tech leadership), one part biased universe, and
  one part testing a long-horizon leverage-constraint anomaly as a
  short-horizon IC factor. You correctly insisted on point-in-time data for
  macro (ALFRED) but not for the equity universe itself — the same principle,
  bigger effect.
- **No cost model.** Every reported number is gross. IC of +0.05 with
  meaningful turnover is plausibly *negative* net of retail spreads,
  commissions, and slippage. Until the harness charges costs, it cannot tell
  you whether anything is tradable, only whether it is interesting.

### 1.4 Informal treatment of multiple testing

The baseline study scanned ~36 cells and found one survivor. At a 5% false
positive rate, chance alone hands you about two. The log shows the right
instinct ("the constant risk is data-mining a backtest into false
confidence") but no machinery enforcing it. Related statistical issues: t-stats
on overlapping forward returns are inflated without Newey–West or
non-overlapping sampling; 36 monthly cuts is a small sample; cross-sectional
ICs treat correlated names as independent observations.

### 1.5 The regime plan, as written, is an overfitting machine

Roadmap item #1 conditions every signal on a growth×inflation quadrant plus
yield curve plus risk-on/off. Conditioning *weak* base signals on multi-state
regimes multiplies researcher degrees of freedom enormously — you will find
regime-conditional gold, and most of it will be noise. The defensible use of
regimes for a project of this sample size is **risk scaling, not sign
flipping**: a dumb, ex-ante, pre-registered regime definition that scales
gross exposure up or down. Letting regimes invert signals (as the low-vol
result tempts you to) is exactly the path to a backtest that only works in
the backtest.

### 1.6 The operator constraint set was never written down

There is no document stating: account size, broker, which instruments are
actually accessible, shorting capability, tax treatment, and daily time
budget. This matters concretely. As an EU retail investor: PRIIPs/KID rules
block most US-domiciled ETFs; shorting single names retail-side mostly means
CFDs with financing costs that eat slow signals; Portugal taxes gains at 28%
and frequent short-term trading risks less favourable treatment. Roadmap
item #2 includes short-squeeze and positioning plays whose short legs may
simply not be executable by this operator at acceptable cost. **An edge the
operator cannot execute is not an edge.** The constraint document should
exist before the next research sprint, because it prunes the hypothesis
space for free.

### 1.7 Unresolved identity tension

Act V concludes, correctly, that durable retail edge is *documented premia
plus discipline almost nobody maintains*. The roadmap then immediately
resumes hunting for a proprietary signal. Both halves are defensible; holding
both at once produces drift. The resolution proposed below: Vigil's *core*
is the discipline/execution/risk engine harvesting boring documented tilts,
and the *lab* is a separate track where candidate edges must pass a formal
gate before promotion. The core has value even if the lab never produces a
star.

### 1.8 Repo hygiene (small but telling)

A file named `worker_token.rtf` sits in the root of a **public** repo, and
the README renders a `<<<<<<< HEAD` merge conflict while describing the
abandoned OpenAlice/Kronos identity. If the token is real, rotate it at the
provider immediately — deleting the file doesn't remove it from history.
This repo may eventually be shown to recruiters; it should look like the
work of someone who handles secrets professionally.

### What was *not* amateur

For balance: building an honest baseline study at all; accepting its verdict
and demoting Kronos; the McLean–Pontiff awareness; the hypothesis-first
instinct; and the Act V conclusion that outsized moves come from catalysts,
flows, and positioning rather than price patterns — that conclusion is
correct and matches both the literature and the empirical record. The
infrastructure lessons (serverless, silent git failures) were paid for
properly and learned properly.

---

## Part 2 — The corrected worldview

Three reframes, from which everything in Part 3 follows.

### 2.1 The realistic prize

"A short daily list of asymmetric opportunities" is the wrong target shape.
The edges actually available to a disciplined retail operator are mostly
**slow, small, and event-driven**: a portfolio of modest documented tilts,
executed at low cost, with risk discipline, realistically landing somewhere
around Sharpe 0.5–1.0 net if everything goes well. The cadence is weekly and
event-driven, not daily. Vigil should stop promising daily asymmetry and
start being the thing that makes a slow strategy survivable: it watches,
sizes, enforces stops, and logs — and *occasionally* surfaces an event.

### 2.2 The most valuable output of Vigil right now isn't alpha

It's two other things. First, the discipline layer — sizing, chosen-stop,
calibrated honesty — which is genuinely differentiated and protects capital
while the search continues. Second, **a credible, public derivatives research
artifact for the front-office job search**, which has higher expected value
to a 22-year-old in mid-2026 than any plausible trading P&L on a retail
account. This reframe should change prioritisation: work that makes Vigil a
better recruiting artifact (rigorous methodology, options pipeline, clean
writeups) is not a distraction from edge-finding; it is co-equal.

### 2.3 The thesis and Vigil are the same project

The single biggest strategic omission in the log: you are writing an MSc
thesis on **option-implied risk-neutral densities and risk preferences**
while hunting for edge in price/volume patterns. Option-implied information
is one of the few signal families with respectable post-publication
survival, precisely because extracting it requires infrastructure and
expertise most retail (and plenty of institutional) players don't have.
Documented families worth knowing cold:

- **Implied-volatility skew predicting cross-sectional returns** (Xing,
  Zhang & Zhao): steep OTM put skew predicts underperformance — informed
  traders act in options first.
- **Implied minus realized vol spread** as a cross-sectional and timing
  signal.
- **Risk-neutral skewness and kurtosis** from option chains (Conrad, Dilts
  & Ghysels; Bakshi–Kapadia–Madan moments — the exact machinery of your
  thesis).
- **Variance risk premium** predicting aggregate market returns
  (Bollerslev, Tauchen & Zhou).
- **Option-implied densities around events** — your literal thesis topic —
  as a lens on earnings and macro announcements.

The data problem is real (OptionMetrics is paywalled) but solvable the
honest way: **start recording option chains yourself, today**. A nightly job
snapshotting chains for ~100–200 liquid US names plus index options (free
delayed sources: yfinance chains, CBOE delayed quotes) builds a
point-in-time options database that is survivorship-free *by construction*.
In six months you have a proprietary dataset nobody can question, the
empirical backbone of your thesis, and the foundation of Vigil's most
promising signal family — all from one cron job. This is the highest
leverage-per-hour item available to you.

---

## Part 3 — The refined plan

### Phase 0 — Stop the bleeding (this week)

1. **Security and hygiene.** Rotate the worker token; purge
   `worker_token.rtf` from git history; fix the README conflict marker and
   rewrite the README to the current identity. Decide whether the repo
   stays public (recommended: yes, it's a portfolio asset — which raises the
   hygiene bar).
2. **Remove Kronos now, not "once the new core carries the pipeline."**
   Dead code is a complexity tax on every future change, and the roadmap
   currently proposes building a regime layer *on top of* a pipeline still
   threaded with forecast plumbing. Excise `kronos_service/`, `serverless/`,
   `kronos_client`, `kronos_features`, `forecast_calibration` and the
   forecast branches of run/report/scoring/sanity/UI in one focused sprint.
   Keep the *calibration methodology* as a library — it will be reused on
   real signals.
3. **Write `CONSTRAINTS.md`.** Account size, broker, accessible instruments
   (the PRIIPs/ETF problem, CFD costs, options access and approval level),
   shorting reality, Portuguese tax treatment, hours per week. Every future
   hypothesis gets checked against it before any code is written.
4. **Write `HYPOTHESES.md` and start pre-registering.** Before testing
   anything: date-stamped entry stating the hypothesis, the economic
   mechanism, the predicted sign, the universe, the horizon, and the
   pass/fail threshold. Tested-and-failed entries stay in the file. This is
   the cheap, honest defence against the data-mining risk the log already
   identified.

### Phase 1 — Harden the lab (2–3 weeks)

The lab is the real asset; make its verdicts trustworthy before asking it
more questions.

1. **Cost model in every output.** Configurable spread + commission +
   slippage assumptions; report gross *and* net everywhere. A signal that
   dies net of costs is dead.
2. **Statistics upgrade.** Newey–West (or strictly non-overlapping samples)
   for overlapping horizons; report the number of hypotheses tested alongside
   any result and apply an FDR-style haircut; adopt a deflated-Sharpe habit
   for any strategy-level backtest.
3. **Point-in-time universe.** Reconstruct historical S&P 500 / mid-cap
   membership (the changes are public — Wikipedia's historical constituent
   change list is a workable free source) so delisted and demoted names exist
   in the test. Where delisting returns are unavailable, document the bias
   direction rather than ignoring it.
4. **Holdout discipline.** Reserve the most recent ~18 months as a vault.
   Nothing touches it until a signal has passed everything else, and each
   signal gets exactly one look.
5. **The lab gate, formalised.** A signal is promoted to the product only
   if: pre-registered → significant after FDR haircut → survives net of
   costs → survives the holdout → is executable under `CONSTRAINTS.md`.
   Write this gate into the repo as policy.

### Phase 2 — The options pipeline (start immediately, runs in background)

1. **Nightly chain-snapshot daemon**: ~100–200 liquid US optionable names
   plus SPX/SPY and a few index/ETF chains; store raw quotes, computed IVs,
   and derived summary stats (ATM IV, 25Δ skew, term slope, BKM implied
   moments). SQLite or parquet; runs on the Mac or the Pi.
2. **First studies once ~3 months of data exist** (and meanwhile, validate
   machinery on whatever free historical IV summaries exist): skew
   cross-section, IV–RV spread, implied-moment sorts. These double as
   thesis empirical work.
3. **Event lens**: snapshot densities around earnings dates — the direct
   thesis tie-in and the most natural "Vigil surfaces an event" use case.

This phase is the convergence point of thesis, CV, and edge search. Protect
it from being deprioritised by shinier ideas.

### Phase 3 — Hunt where edges actually survive (after Phase 1)

Priority-ordered, each pre-registered, each checked against constraints:

1. **PEAD on small / under-covered names.** Post-earnings announcement
   drift is among the best post-publication survivors, specifically in low-
   coverage, high-limits-to-arbitrage names — and it's long-side tradable,
   which fits the constraint set. Needs an earnings calendar + surprise data
   pipeline (free-tier sources: Finnhub, Alpha Vantage, Yahoo).
2. **Trend/expectancy in FX and commodities.** Your one surviving cell
   (`forex@30` expectancy) being a *trade-structure* effect is consistent
   with the entire CTA literature: trend-following profitability is mostly
   payoff asymmetry (cut losers, ride winners), not direction-prediction
   skill. This reframes the finding from "anomaly that survived" to "a
   documented premium you independently rediscovered" — which is exactly the
   kind of signal Act V says Vigil should harvest. Test classic time-series
   momentum with your chosen-stop structure, net of realistic FX/CFD costs.
3. **COT positioning extremes** (free CFTC data) as a *conditioning*
   variable on the trend sleeve rather than a standalone signal — extremes
   are documented but weak alone.
4. **Index/flow events** last: rebalance front-running is heavily arbitraged
   now; treat it as a curiosity unless the lab is surprised.

Deliberately demoted: generic short-squeeze plays (short-side execution
constraints), 13F cloning (stale by filing, crowded), and any further
price-only pattern mining (the lab already issued its verdict; believe it).

### Phase 4 — Regimes, the modest version (after Phases 1–3 produce something to scale)

One dumb, pre-registered regime indicator (e.g., a composite of yield-curve
slope and a trailing risk-on/off measure from ALFRED point-in-time data)
that does exactly one thing: scales gross exposure between, say, 0.5× and
1.0×. No sign flips, no per-signal conditioning, no quadrant taxonomy until
there are years more data. Evaluate it on drawdown reduction, not return
enhancement.

### Ongoing from day one — the forward ledger

Start the paper-trade → realised-performance loop *now*, even with imperfect
signals, rather than as roadmap item #6. Forward paper results are the only
data with zero look-ahead bias by construction, the loop exercises the whole
discipline stack (sizing, stops, Telegram, logging), and the ledger itself
becomes part of the recruiting artifact: "here is my live, timestamped,
out-of-sample record, including the losses." Honesty in public is rare and
it reads as exactly what it is.

---

## The one-paragraph version

Vigil's real product is discipline plus a truth-telling lab; accept that and
stop hunting for a daily oracle. Fix the lab's three blind spots (costs,
survivorship, multiple testing) before trusting another verdict from it.
Kill Kronos this week, not later. Write down the operator constraints,
because they delete half the roadmap for free. Then put the search effort
where edges demonstrably survive publication *and* match your actual
expertise: option-implied information — built on a chain-recording pipeline
you start tonight — plus PEAD in under-covered names and trend/expectancy
structure in FX and commodities. Use regimes only to scale risk. Run the
forward ledger from day one. And treat the repo as what it also is: the
derivatives research portfolio piece your front-office applications are
currently missing.
