# VIGIL — Metric Glossary (what every number means)

Plain-English definitions of everything Vigil shows. Grouped by where it appears.
Scale and interpretation noted; the specialized ones get extra explanation.

---

## Headline (top of a pick)

- **Vigil score (0–100)** — Vigil's overall ranking number. A weighted blend of
  conviction, the path-cloud edge, calibrated probability, technical alignment and
  quality. Higher = Vigil likes it more. It's a *prior*, not a guarantee.
- **Conviction (1–5 stars)** — the LLM analyst's holistic confidence. 3 is the honest
  average; 4–5 means genuinely strong across multiple dimensions.
- **Direction (LONG / SHORT)** — whether the trade is to buy (profit if it rises) or
  short (profit if it falls). Chosen from the forecast.
- **Horizon (low / medium / high)** — the auto-selected timeframe. low ≈ days
  (technical), medium ≈ weeks (swing), high ≈ a month+ (position). Longer = less certain.
- **Strategy type** — *momentum* (trade with the trend), *mean_reversion* (bet a
  stretched move snaps back), *breakout* (new range), *value* (cheap fundamentals).

## Forecast (from Kronos, the price model)

- **Kronos ret / Expected return %** — the central (median) projected % move over the
  horizon. The single most overstated number — treat the *direction* as more reliable
  than the *magnitude*.
- **Probability up (prob_up)** — chance the price is higher at the horizon. Clamped to
  2–98% (nothing is ever truly certain). For a short, you want this LOW.
- **90% low / high (ret_q05 / ret_q95)** — the 90% confidence interval for the return:
  9 times out of 10 the outcome should land in this band. Wider = more uncertain.
- **Terminal vol** — the forecast's volatility (standard deviation) at the horizon, in %.
  It sets the width of the cone.
- **Cone (fan chart)** — the shaded band on the chart: the spread of possible price
  paths (q05–q95 around the median). Fat cone = low confidence.

## Decision shapers / technicals

- **Fund score (0–100)** — fundamentals quality (valuation, growth, profitability,
  balance sheet, analyst tilt, value frameworks). Higher = financially stronger.
- **Tech score (0–100)** — strength of the *bullish* technical setup.
- **RSI(14) — Relative Strength Index** — momentum oscillator, 0–100. Below ~30 =
  oversold (may bounce); above ~70 = overbought (may pull back); 40–60 = neutral "room".
- **MACD hist** — Moving Average Convergence/Divergence histogram. Momentum gauge:
  positive & rising = strengthening upside; negative = weakening / downside.
- **ATR(14) — Average True Range** — average daily price range in dollars; a volatility
  measure used to size stops (e.g. a stop 1–3 ATRs away).
- **vs SMA50 / vs SMA200** — % above/below the 50- and 200-day Simple Moving Averages
  (the average price over that many days). Above both = uptrend; below = downtrend.
- **vs 52w high / low** — how far the price is from its 1-year extremes.
- **Max DD 1Y — Maximum Drawdown** — the worst peak-to-trough fall over the last year, %.
- **ADX — Average Directional Index** — trend *strength*, NOT direction. Below ~20 =
  choppy/rangey; above ~25 = a real trend is in force (up or down).
- **Confluence (n/5)** — how many independent signals agree on the setup. More = stronger.
- **Trailing stop (3·ATR chandelier)** — a volatility-based exit that trails the price by
  3 ATRs; the "chandelier" stop is a standard trend-following exit.

## Barrier probabilities (Kronos paths × your levels)

Simulated by running the forecast's path cloud against your entry/stop/target:

- **P(target first)** — probability the price touches your target before your stop.
- **P(stop first)** — probability it hits your stop first.
- **P(neither)** — probability it does neither by the horizon.
- **Expected R · prob-weighted** — the *expected reward-to-risk multiple*. NOT a
  probability — it can exceed 1. = (reward ÷ risk) × P(target) − P(stop). Positive means
  the bet has favourable expectancy after weighing both outcomes.
- **~days to target** — average simulated days to reach the target when it's hit.

## Kronos features (path-cloud statistics)

- **Predicted range** — expected high-minus-low spread over the horizon, %.
- **Max adverse (MAE — Maximum Adverse Excursion)** — the expected *worst* dip along the
  way (how much it goes against you before the end). Helps judge if your stop is realistic.
- **Max favorable (MFE — Maximum Favorable Excursion)** — the expected *best* move in your
  favour along the way.
- **Skew** — asymmetry of outcomes. Positive = a fatter upside tail (rare big gains);
  negative = fatter downside tail.
- **CVaR 5% — Conditional Value at Risk (expected shortfall)** — the *average* of the worst
  5% of outcomes. "If things go badly (worst 1-in-20), how bad on average?" More negative
  = nastier tail risk than a simple worst-case.
- **Ret/vol** — return per unit of volatility (a mini Sharpe). Higher = better risk-adjusted.
- **Vol trend** — predicted slope of trading volume (rising participation or fading).
- **P(up > 5%)** — probability of at least a 5% upside move.

- **Kronos quality (0–100)** — for assets with no fundamentals (FX/crypto/commodities):
  a quality score built only from the forecast (direction confidence + risk-adjusted
  return + skew + downside containment).

## Position sizing

How much to allocate (advisory). Set `VIGIL_ACCOUNT_EQUITY` to get dollar amounts.

- **Suggested weight %** — the recommended position size as a % of your account.
- **Full Kelly %** — the **Kelly criterion**: the mathematically growth-optimal bet
  fraction given your edge and odds. It is *aggressive* (assumes you know the edge
  exactly), so Vigil uses **half-Kelly** and caps it.
- **Vol-target wt** — the size that would make this position's volatility hit a target
  (default 15%/yr). Caps risky names.
- **Binding constraint** — which limit actually set the size: *kelly* (your edge),
  *vol_target* (volatility cap), *max_position* (the 25% hard ceiling), or *no_edge*
  (no positive expectancy → 0%).

## Value frameworks (fundamentals)

- **Piotroski F-score (0–9)** — a 9-point accounting-quality checklist (profitability,
  leverage, efficiency, all year-over-year). 7–9 = financially improving; 0–3 = weak.
- **Greenblatt (Magic Formula)** — ranks on *earnings yield* (cheapness) + *return on
  capital* (quality). High on both = a good-and-cheap company.
- **Graham criteria** — Benjamin Graham's classic defensive-value checklist (low P/E, low
  P/B, current ratio ≥ 2, positive earnings, dividend, etc.).
- **Earnings yield** — earnings ÷ price (the inverse of P/E). Higher = cheaper.
- **Return on capital (ROC)** — profit relative to the capital employed; a quality gauge.
- **P/E** — price ÷ earnings (how many years of earnings you pay for). **P/B** — price ÷
  book value. **PEG** — P/E ÷ growth (P/E adjusted for growth; <1 is attractive).
- **Debt/equity** — leverage; lower = safer balance sheet.

## Context

- **Regime (risk-on / risk-off / neutral)** — coarse market weather from the VIX (the
  "fear index"). Risk-on = calm, favour momentum; risk-off = stressed, favour quality.
- **Vigil score breakdown** — shows each component's sub-score and weight, so you can see
  *why* a pick scored what it did.
- **AI critic / Consistency check** — two auditors: a deterministic one (math invariants)
  and an LLM one (financial sense). If either flags a pick, treat its numbers with caution.
