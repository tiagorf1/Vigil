# Vigil
<<<<<<< HEAD
Project
=======

*Markets Watch.* A local investment opportunity scanner. Builds a candidate
universe from **OpenAlice** market data (or a free Yahoo fallback), screens it on
fundamentals and technicals, forecasts the survivors with the **Kronos** price
model, synthesises a ranked watchlist of research reports — viewable in a local,
FT-styled web UI — and pushes **Telegram signals** to your phone when something
clears the bar.

> The Python package is still imported as `scanner` (stable internal name); the
> product is **Vigil**.

It is a research and idea-generation tool. It does not execute trades. All
output is advisory.

```
directive ──▶ universe ──▶ screen ──▶ Kronos forecast ──▶ report ──▶ watchlist + UI
            (OpenAlice)   (fund+tech)   (batched, prob.)   (LLM)
                              ▲                                  │
                     portfolio + macro + earnings ──────────────┘
```

**Key features**
- **Probabilistic forecasts** — each name is a Monte-Carlo cloud of Kronos paths,
  giving `P(up)`, a 5–95% return cone, and forward volatility (not just a point).
- **Adjustable forecast depth** — choose the forecast horizon and Monte-Carlo path
  count from the UI or CLI (`--pred-len`, `--mc-paths`) for quick or deep scans.
- **Batched inference** — all survivors forecast in one GPU pass (`predict_batch`).
- **Portfolio aware** — reads your OpenAlice positions, tags held names, and emits
  exit signals on holdings whose forecast turned negative.
- **Horizon + reasons** — every report includes a low/medium/high horizon bucket,
  concrete "why now" reasons, and local performance metrics.
- **Macro + events** — FRED rates/dollar/CPI backdrop; earnings-in-window tags.
- **Vol-sized stops** — risk levels sized from Kronos forward vol, not just ATR.
- **Calibration** — scores past forecasts vs realized prices (hit-rate / Brier).
- **Local indicators + caching** — technicals computed in pandas from one OHLCV
  fetch; fundamentals cached daily. Concurrent reports with rate-limit backoff.
- **Sector-diversified** watchlist; pluggable LLM (gemini / anthropic / none).

See `TUTORIAL.md` for a full feature walkthrough, `PROCESSING_ROUTES.md` for
off-machine processing options, and `NEXT_IDEAS.md` for the roadmap.

Remote worker scaffold:

```bash
python -m scanner.worker   # run on a remote box, default port 8090
```

## Indexes, Telegram signals & 24/7

**Index components.** Index scans use liquid ETF handles as benchmarks (`SPY`,
`QQQ`, `DIA`, plus sector sleeves on broad US scans) but analyze the component
companies as investment ideas. Run from
the UI's section nav or the CLI:

```bash
python -m scanner.run "s&p 500" --asset-class index
python -m scanner.run "nasdaq 100" --asset-class index
```

`--offline` uses a **free Yahoo Finance fallback** for price data, useful for
technical-only tests. Full equity component scans are strongest with OpenAlice
running because fundamentals/news/earnings come from OpenAlice. Local mode is
safety-capped by `MAX_INDEX_COMPONENTS_LOCAL` before screening and
`MAX_SCREENED_SIZE` before Kronos/reporting, so S&P scans do not try to forecast
all 500 names on this Mac.

**Telegram signals.** Get a message on your phone when a scan finds something:

1. In Telegram, message **@BotFather** → `/newbot` → copy the token.
2. Message your new bot once, open
   `https://api.telegram.org/bot<TOKEN>/getUpdates`, copy your numeric chat id.
3. Put both in `.env` as `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`.

Signals fire automatically after a scan when a pick clears `SIGNAL_MIN_CONVICTION`
or `SIGNAL_MIN_RETURN` (or on any exit signal). Force one with `--notify`, mute
with `--no-notify`.

Signal markets now include brokerage-friendly global ETF baskets, commodities,
forex, and crypto:

```bash
SIGNAL_MARKETS=global-liquid
python -m scanner.signals
```

**24/7 for free (no always-on machine).** `.github/workflows/vigil-signals.yml`
runs scheduled market scans on **GitHub Actions** and pushes Telegram signals to
your iPhone — free, in the cloud, using the offline Yahoo data path.
Add `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` (and optionally `GEMINI_API_KEY`) as
repo Actions secrets, push, and edit the `cron:` line to taste. The default cloud
profile is `global-liquid`: liquid index ETFs, commodity ETFs, major FX pairs,
and crypto majors at a 90-day / 24-path forecast depth.

## Setup (under 10 steps)

1. **Clone the two upstream repos as siblings** (do not modify them):
   ```bash
   cd ~
   git clone https://github.com/shiyu-coder/Kronos.git
   git clone https://github.com/TraderAlice/OpenAlice.git
   ```
2. **Install Kronos Python deps:** `cd ~/Kronos && pip install -r requirements.txt`
3. **Install scanner deps:** from this repo, `pip install -r requirements.txt`
   (PyTorch is carried by your Kronos env; if missing, install CPU torch — see
   `requirements.txt`).
4. **Build + start OpenAlice** (needs Node 22+ and pnpm 10+):
   ```bash
   corepack enable pnpm           # if pnpm is missing
   cd ~/OpenAlice && pnpm install && pnpm build && pnpm dev
   ```
   Note the **MCP port** it prints (default `47332`). Ports auto-bump if taken.
5. **Configure:** `cp .env.example .env` and fill in:
   - `LLM_PROVIDER` — `gemini` (free, default), `anthropic`, or `none` (no key).
   - `GEMINI_API_KEY` — free key from <https://aistudio.google.com/apikey>.
   - `OPENALICE_MCP_URL` — match the port OpenAlice printed.
   - `KRONOS_REPO_PATH` — path to the cloned Kronos tree (default `~/Kronos`).
   - `KRONOS_SERVICE_URL` — optional remote Kronos service to offload forecasting.
6. **Run it — three ways:**

   **A. Full stack, one double-click** — double-click
   **`Vigil Full Stack.command`** (macOS). It starts OpenAlice and Vigil, writes
   logs to `logs/`, and opens the browser. Kronos starts on the first forecast by
   default to avoid heating the machine at idle; set `VIGIL_WARM_KRONOS=true` if
   you prefer warming the model at launch. Set `OPENALICE_DIR` in `.env` if your
   OpenAlice clone is not at `~/OpenAlice`.

   **B. Browser control panel only** — double-click
   **`Vigil.command`** (macOS), or run `python -m scanner.server`. Your browser
   opens to a control panel: type a directive, pick options, hit **RUN SCAN**, and
   watch live progress. Past scans are in the History dropdown; the clock icon runs
   calibration.
   A selected report can be pushed directly to OpenAlice Inbox with **Send to
   Alice**, while **Push to Inbox** still sends the whole watchlist.

   **C. CLI:**
   ```bash
   python -m scanner.run "European banks"
   python -m scanner.run "AAPL MSFT NVDA"        # explicit symbols
   python -m scanner.run "" --asset-class crypto # broad crypto sweep
   python -m scanner.run "AAPL" --provider none  # no API key needed
   python -m scanner.run "AI infra" --push-inbox # push watchlist to OpenAlice Inbox
   python -m scanner.run "AI infra" --stage-orders  # STAGE (not execute) orders for review
   python -m scanner.run "SPY" --pred-len 90 --mc-paths 24
   ```
   The Kronos service starts automatically on first use (first run downloads the
   model, ~115 MB).
7. **View the watchlist** — the UI opens in your browser automatically. To open
   it manually: `python -m http.server 8080` then visit
   <http://localhost:8080/ui/index.html>.
8. **(Later) Calibrate** once picks have matured past their forecast horizon:
   ```bash
   python -m scanner.calibrate    # writes outputs/calibration.json; hit% shows in UI
   ```

## How it works

| Stage | Module | Notes |
|---|---|---|
| Universe | `scanner/universe.py` | OpenAlice search; curated seed list for empty directive |
| Screen | `scanner/screener.py` | Fundamental + technical scoring, 0–100 each, run concurrently |
| Forecast | `scanner/kronos_client.py` + `kronos_service/` | Warm FastAPI model service on `:8765` |
| Synthesis | `scanner/report_generator.py` | Pluggable LLM: gemini / anthropic / none |
| Output | `scanner/output.py` | Ranked JSON + markdown; `outputs/latest.json` drives the UI |

## LLM provider choice

The only place an LLM is used is the report synthesis step. Set `LLM_PROVIDER`:

- **`gemini`** (default) — Google AI Studio free tier. Note: free-tier inputs may
  be used by Google to improve their products.
- **`anthropic`** — Claude, stronger synthesis, paid. Needs `ANTHROPIC_API_KEY`.
- **`none`** — deterministic template report, no key, no cost. The full
  universe→screen→forecast→rank pipeline still runs.

Override per run with `--provider`.

## Tests

```bash
pytest tests/ -v                              # unit tests (no live services)
pytest tests/test_integration.py --integration  # needs live OpenAlice + Kronos
```

## Layout

```
scanner/         core pipeline (config, openalice_client, universe, screener,
                 kronos_client, report_generator, output, run)
kronos_service/  FastAPI wrapper that keeps the Kronos model warm
ui/              single-file web UI (no build step)
outputs/         generated watchlists (gitignored; latest.json is the UI source)
tests/           unit + integration tests
```

## Troubleshooting

- **"OpenAlice MCP not reachable"** — start `pnpm dev` in `~/OpenAlice` and set
  `OPENALICE_MCP_URL` to the MCP port it printed.
- **Empty / sparse watchlist** — usually OpenAlice tool output shape differs from
  what the client expects. Run a scan and check the logged tool catalog; the
  client resolves tool names dynamically and degrades gracefully, but the
  price-history tool name in particular may need adjusting in
  `openalice_client.get_ohlcv`.
- **Kronos slow** — CPU inference is ~30–60s/symbol; Apple `mps` / CUDA is far
  faster. Set `KRONOS_DEVICE` in `.env` to force a device.
>>>>>>> fe5d6a0 (Initial Vigil scanner)
