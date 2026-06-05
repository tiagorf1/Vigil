# Scanner — Usage Tutorial & Feature Walkthrough

This walks you from a cold start to a full scan, then explains every feature in
the output. Assumes you've cloned `~/Kronos` and `~/OpenAlice` (see README).

---

## 0. One-time setup

```bash
# Terminal A — start OpenAlice (the market-data source). Leave it running.
corepack enable pnpm          # if pnpm is missing
cd ~/OpenAlice && pnpm install && pnpm build && pnpm dev
# Note the MCP line it prints, e.g. [dev] MCP -> http://localhost:47332/mcp

# Terminal B — the scanner
cd "~/Scanner Project"
pip install -r requirements.txt
cp .env.example .env          # then edit: set GEMINI_API_KEY (already set for you),
                              # and OPENALICE_MCP_URL to match the port above
```

Your `.env` is already configured with `LLM_PROVIDER=gemini` and your key. To run
with no API at all, set `LLM_PROVIDER=none`.

---

## 1. Your first scan

### The easy way — no terminal (recommended)

Double-click **`Vigil.command`** (macOS) — or run `python -m scanner.server`
once. Your browser opens to the **control panel**:

1. Type a directive in the prompt (e.g. `European banks`, or `AAPL MSFT NVDA`).
2. Pick the asset class (Auto / Equity / Crypto) and provider (or leave defaults).
3. Optional: the gear sets *push to Inbox*, *stage orders*, and *max results*.
4. Hit **RUN SCAN**. A 6-stage stepper shows live progress; the watchlist appears
   when done.

The header LEDs show whether OpenAlice and Kronos are reachable. The **History**
dropdown reloads any past scan; the clock icon runs **calibration**. The
**My portfolio** nav stores a local list in `portfolio.json`, and each report has
a **+ Portfolio** button. Everything below works the same whether you launched
from the panel or the CLI.

### The CLI way

```bash
python -m scanner.run "AAPL MSFT NVDA"
```

What happens, stage by stage (you'll see these printed):

```
[1/6] Building universe for 'AAPL MSFT NVDA'...   # explicit tickers -> used directly
      Portfolio: 4 held positions                 # pulled from OpenAlice (if any)
[2/6] Screening 3 candidates...                   # fundamental + technical, scored 0-100 each
[3/6] Screen survivors: 3 names
[4/6] Kronos forecasting 3 names (batched)...     # ONE batched GPU pass, not 3
      Holdings review: forecasting 1 held names...  # forecasts names you own but didn't screen
[5/6] ...                                          # (exit signals computed here)
[6/6] Generating reports (gemini)...               # concurrent, with rate-limit backoff
Done. Watchlist: 3 names, 1 exit signals -> outputs/watchlist_20260605_...json
UI: http://127.0.0.1:8080/ui/index.html            # opens automatically
```

The browser opens to the terminal-style UI. The Kronos service starts itself on
first use (first run downloads the model, ~115 MB).

### Other ways to invoke

```bash
python -m scanner.run "European banks"            # natural-language directive
python -m scanner.run "" --asset-class crypto     # broad crypto sweep (seed list)
python -m scanner.run --from-file symbols.txt     # one ticker per line
python -m scanner.run "semis" --max-results 5     # cap the watchlist
python -m scanner.run "AAPL" --provider none      # no API key, template report
python -m scanner.run "tech" --no-ui              # skip the browser
```

---

## 2. Reading the UI

### Header
- **directive / timestamp** — what you scanned and when.
- **macro strip** — `DGS10` (10y Treasury yield), `DTWEXBGS` (dollar index),
  `CPIAUCSL` (CPI), pulled from OpenAlice's FRED tools. Your regime backdrop.
- **stats** — scanned → screened → picks, the synthesis provider, and once you've
  run calibration, a **hit %** (forecast accuracy on matured picks).

### Left panel — watchlist
Each row: rank, ticker, conviction stars, strategy badge, and on the right:
- **expected return** (Kronos mean) and **P↑** — the probability the name is
  higher at the horizon, computed across the Monte-Carlo path cloud.
- **HELD** badge if you already own it (from your OpenAlice portfolio).
- **R/R** — reward-to-risk from the strategy levels.
- **horizon badge** — `low`, `medium`, or `high`, so you can separate tactical
  trades from longer fundamental setups. The chips above the list filter by this.

An **EXIT SIGNALS** box appears at the top if any *held* name has a negative
forecast — your "consider trimming" list.

### Right panel — report
- **THESIS** — the LLM's synthesis (or a template if `provider=none`).
- **WHY NOW** — 4–6 concrete reasons the setup made the watchlist.
- **PERFORMANCE** — local price/volatility context such as 1m/3m returns,
  annualized volatility, drawdown, 52-week distance, RSI, and SMA distance.
- **FUNDAMENTALS / TECHNICALS / FORECAST** — three columns. The forecast column
  shows the **fan chart**: the shaded band is the 5–95% Kronos cone, the line is
  the median path. Below it, `P↑` and the 90% return range.
- **STRATEGY** — Entry / Stop / Target / R-R. The stop is labelled **(vol-based)**
  when it was sized from Kronos's forward volatility, **(ATR-based)** when from
  historical ATR.
- **RISKS** and **TAGS** — tags include the sector, `held`, and
  `earnings_in_window` (a forecast that straddles an earnings date — handle with
  care).

---

## 3. Feature deep-dive

### Probabilistic forecasting (the big one)
Instead of a single predicted line, each symbol is run through Kronos as a cloud
of stochastic paths. Use the UI options or CLI flags (`--pred-len`, `--mc-paths`)
to choose the forecast horizon and Monte-Carlo depth for a run. From that
distribution:
- `prob_up` — share of paths ending higher.
- `ret_q05/q50/q95` — the 5th / 50th / 95th percentile return (the 90% range).
- `step_vol` / `terminal_vol` — forward volatility, used to size stops.
- `cone` — per-step quantile bands that draw the fan chart.

A name with `+8% expected` but `P↑ 52%` is a wide, uncertain setup; `+8%` with
`P↑ 80%` is tight conviction. The point forecast alone hides that.

### Portfolio awareness
The scanner reads your OpenAlice positions, and also supports a lightweight local
portfolio from the UI. Held names are tagged, and the scanner runs a
**holdings review** — forecasting what you own and flagging negative-forecast
positions as exit signals. Idea-generation plus position-monitoring in one pass.

### Macro + events
`DGS10`/`DTWEXBGS`/`CPIAUCSL` give a rates/dollar/inflation backdrop. For
equities, the earnings calendar is checked and names reporting inside the
forecast window are tagged `earnings_in_window`.

### Calibration — is Kronos any good?
After picks have had time to mature (the 20-day horizon elapses), run:

```bash
python -m scanner.calibrate
```

It compares past forecasts in `outputs/` to realized prices and writes
`outputs/calibration.json`: **hit_rate** (direction accuracy), **mae_ret_pct**
(return error), and **brier** (probability calibration; 0.25 = coin flip). The
hit % then shows in the UI header. This is what anchors "conviction" to reality.

### Integration with OpenAlice
```bash
python -m scanner.run "AI infrastructure" --push-inbox
```
Pushes the watchlist to OpenAlice's **Inbox** so Alice (the agent) can reference
it in chat and manage follow-up.

```bash
python -m scanner.run "AI infrastructure" --stage-orders
```
**Stages** (does NOT execute) limit orders for conviction-4+ picks in OpenAlice,
for you to approve or discard in its UI. Nothing trades automatically — this only
queues orders for your explicit confirmation. Off by default.

### Telegram signal markets
`SIGNAL_MARKETS` in `.env` controls the scheduled signal runner. Examples:

```bash
SIGNAL_MARKETS=world
SIGNAL_MARKETS=us,crypto,portfolio
python -m scanner.signals              # uses SIGNAL_MARKETS
python -m scanner.signals europe asia  # one-off override
```

`portfolio` means "check my current holdings for sell signals"; market names run
fresh offline scans and notify only when a pick clears your signal thresholds.

---

## 4. Performance notes

- **Batched forecasting**: all survivors forecast in one GPU pass via Kronos's
  `predict_batch`, chunked for memory. On Apple `mps` a ~30-name scan's forecast
  stage is tens of seconds, not minutes.
- **Local indicators**: technicals are computed in pandas from a single OHLCV
  fetch per symbol — roughly 6x fewer OpenAlice calls than per-indicator round
  trips, and no dependency on an unknown indicator-response shape.
- **Caching**: profiles, financials, ratios, and earnings dates are cached to
  `.cache/` for a day, so re-runs and scheduled scans skip re-fetching.
- **Concurrent reports + backoff**: report generation runs ~8 in flight with
  exponential backoff, so Gemini's free-tier rate limit doesn't stall a scan.

---

## 5. Troubleshooting

| Symptom | Fix |
|---|---|
| "OpenAlice MCP not reachable" | Start `pnpm dev`; set `OPENALICE_MCP_URL` to the printed port. |
| Empty / sparse watchlist | Check the logged tool catalog on the first scan; the OHLCV tool name may need pinning in `openalice_client.get_ohlcv`. |
| Gemini 429s | Expected on free tier; backoff handles it. Or `--provider none`. |
| Forecast stage slow | First run loads the model. Set `KRONOS_DEVICE` to force `mps`/`cuda`. |
| Calibration says "no matured forecasts" | Normal until the saved forecast horizon elapses on past picks. |
