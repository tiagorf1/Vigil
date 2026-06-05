# Scanner — Codex context

This file orients future Codex sessions. The full original specification
follows the status section below.

## Upgrade pass (post-initial-build) — COMPLETE and verified

Shipped on top of Phase 1/2:
- **Batched probabilistic Kronos** (`kronos_service/predictor.py` `forecast_batch`,
  `/forecast_batch`): Monte-Carlo path cloud -> `prob_up`, q05/q50/q95 return,
  forward vol, per-step `cone`. Verified live (24 paths in ~12s on mps).
- **Local indicators** (`scanner/indicators.py`): RSI/MACD/SMA/ATR/BBands in
  pandas from one OHLCV fetch; screener no longer calls `calculateIndicator`.
- **Portfolio/macro/events/integration** (`openalice_client`): `get_positions`,
  `get_earnings_calendar`, `get_macro` (FRED/BLS), `push_inbox`, `stage_order`,
  plus a daily `DiskCache` (`scanner/cache.py`) for fundamentals.
- **Report/output**: vol-sized stops, probabilistic context, Gemini
  `response_schema`, retry/backoff; sector-diversification cap, macro block,
  exit signals, held flags, fan-chart cone in the UI.
- **Calibration** (`scanner/calibrate.py`): self-scores past outputs vs realized
  prices -> `outputs/calibration.json` (hit-rate / MAE / Brier), shown in UI.
- **run.py** orchestrates all of it: batched forecasts (reusing screener OHLCV),
  concurrent reports, holdings review, `--push-inbox` / `--stage-orders`.
- Tests: 22 unit pass (added test_indicators, test_cache, batch + diversify).
- New env var `KRONOS_MC_PATHS` (default 12). See TUTORIAL.md and NEXT_IDEAS.md.

`--stage-orders` only STAGES orders for human approval in OpenAlice; nothing
executes automatically.

### Control panel + redesign (this session)
- **`scanner/server.py`** — FastAPI control panel. Serves the UI, `POST /api/scan`
  (background thread runs the pipeline; progress streamed via `run.STATUS_CALLBACK`),
  `GET /api/status|outputs|watchlist|health`, `POST /api/calibrate`. Run with
  `python -m scanner.server` or double-click **`Scanner.command`**. **(live-verified)**
- **`ui/index.html`** fully redesigned (frontend-design skill): precision-instrument
  aesthetic — phosphor-lime on near-black, Archivo display, Fraunces serif thesis,
  JetBrains Mono data; control bar (directive + asset toggle + provider + options +
  RUN), live 6-stage stepper, fan-chart cone, exits, macro ticker, health LEDs,
  history selector. API-aware with a static `outputs/latest.json` fallback.
- See **FEATURES.md** (full capability list) and **TUTORIAL.md** (walkthrough).

### Vigil rebrand + indexes + Telegram + 24/7 (this session)
- **Rebranded to Vigil** (product name). UI masthead/title + `Vigil.command`
  launcher. Python package stays `scanner` (internal).
- **UI restyled to an FT homage**: salmon paper, Source Serif + Hanken Grotesk,
  claret/teal accents, conventional green/red P&L, hairline rules, and a
  **section-index nav** with one-click market scans. **(live-verified)**
- **World indexes**: `INDEX_PRESETS` (world/us/europe/asia, Yahoo symbols) in
  universe.py; asset_class `index` scored like crypto (momentum). UI nav chips +
  `--asset-class index`. **(live-verified: real index forecasts)**
- **Telegram signals**: `scanner/notify.py` (+ config TELEGRAM_*, SIGNAL_MIN_*);
  auto-sends after a scan when picks clear the bar; `--notify` / `--no-notify`.
- **Free data fallback**: `scanner/market_data.py` uses Yahoo Finance chart API
  (no key) when OpenAlice has no OHLCV. `--offline` runs with NO OpenAlice
  (Stooq was dropped — it now needs an API key). **(live-verified)**
- **24/7 free**: `.github/workflows/vigil-signals.yml` — GitHub Actions daily
  cron runs an offline world-index scan and Telegram-pushes signals.
- 22 unit tests still pass.

## Build status (as of initial build)

**Phase 1 (core pipeline): COMPLETE and verified.**

- `kronos_service/` — predictor + FastAPI wrapper. Verified live: model loads on
  Apple `mps` in ~2s (Kronos-small, 24.7M params); a real 20-candle forecast on
  synthetic data returns in ~6s with all summary stats.
- `scanner/` — config, openalice_client (MCP), universe, screener,
  kronos_client, report_generator, output, run. All import cleanly.
- `ui/index.html` — single-file terminal-style UI. Renders `outputs/latest.json`.
  A SAMPLE watchlist is already saved there for viewing.
- `tests/` — 13 unit tests pass; integration test gated behind `--integration`.

**Not yet run end-to-end live** because it needs OpenAlice's `pnpm dev` server up.
The pipeline degrades gracefully when data is missing.

## Key implementation decisions (deviations from / additions to the spec)

1. **LLM provider is pluggable** (`LLM_PROVIDER` = gemini | anthropic | none),
   not hardcoded to Codex. Default is **Gemini free tier**; `none` is a
   deterministic template report needing no API key. The spec's exact system
   prompt and JSON schema are preserved across all providers. SDK: `google-genai`.
2. **OpenAlice tool names are resolved dynamically.** On connect the client calls
   `list_tools()` and matches intents to the real catalog, surviving renames.
   The price-history (OHLCV) tool is NOT named in the spec — `get_ohlcv` tries
   several plausible names; confirm the real one against the logged catalog once
   OpenAlice is live and pin it in `openalice_client.get_ohlcv`.
3. **OpenAlice ports confirmed** at `47331` (backend) / `47332/mcp` — the spec's
   defaults are correct (verified against the OpenAlice README).
4. **The screener fetches data once** and carries it forward to the report
   generator (avoids double MCP fetches). OHLCV for Kronos is fetched only for
   screen survivors.
5. **Lenient screen fallback:** if fewer than 3 names clear both thresholds
   (common with sparse data), all candidates are ranked by combined score so the
   pipeline still produces a watchlist. Logged when it triggers.
6. **Indicator parsing is shape-tolerant** — calculateIndicator's exact response
   shape is unknown until OpenAlice is live; parsers cover common shapes and
   score 0 (not crash) on anything unrecognised.

## First thing to do when OpenAlice is running

```bash
python -m scanner.run "AAPL MSFT NVDA" --provider none
```
Watch the logged OpenAlice tool catalog. If `get_ohlcv` / indicators come back
empty, adjust the candidate tool names / arg shapes in `scanner/openalice_client.py`
to match what the catalog actually exposes.

## Phases 2 and 3

Phase 2 (UI) is built. Phase 3 (scheduler + OpenAlice inbox integration +
sparkline polish) is not started — see the spec below.

---

# SCANNER — Master Build Plan
## A Kronos + OpenAlice Investment Opportunity Scanner

**Purpose of this document:** Complete specification for Codex to build the scanner
end-to-end. Read this entire file before writing any code. Every architectural decision
is explained so you can work autonomously across sessions without losing context.

---

## What We Are Building

A local investment scanner called **Scanner** that:

1. Accepts a scan directive from the user — a sector, market, keyword, asset class, or
   nothing (full sweep)
2. Builds a candidate universe by querying OpenAlice's market data tools
3. Filters that universe through fundamental and technical screens
4. Runs Kronos price forecasting on the surviving names
5. Uses Codex to synthesise each surviving name into a structured report with a suggested
   strategy
6. Outputs a ranked watchlist — each entry containing: summary card, full report, and
   strategy note
7. Displays everything in a clean local web UI

The scanner is a **research and idea-generation tool**. It does not execute trades
automatically. All output is advisory.

---

## Repository Layout

Create a new repo called `scanner/` at the same directory level as `OpenAlice/` and
`Kronos/`. Do not modify either upstream repo.

```
scanner/
├── AGENTS.md                  ← this file (copy here so Codex finds it)
├── README.md
├── .env.example
├── .gitignore
│
├── scanner/                   ← Python package (core logic)
│   ├── __init__.py
│   ├── config.py              ← central config loader
│   ├── universe.py            ← universe builder
│   ├── screener.py            ← fundamental + technical screens
│   ├── kronos_client.py       ← Kronos inference wrapper
│   ├── report_generator.py    ← Codex synthesis layer
│   ├── output.py              ← watchlist serialiser
│   └── run.py                 ← CLI entry point
│
├── kronos_service/            ← thin FastAPI wrapper around Kronos
│   ├── __init__.py
│   ├── main.py
│   └── predictor.py
│
├── ui/                        ← local web frontend (plain HTML/CSS/JS, no framework)
│   ├── index.html
│   ├── style.css
│   └── app.js
│
├── outputs/                   ← generated watchlists (gitignored)
│   └── .gitkeep
│
├── tests/
│   ├── test_universe.py
│   ├── test_screener.py
│   └── test_kronos_client.py
│
├── pyproject.toml
└── requirements.txt
```

---

## External Dependencies

### OpenAlice
- **Already running** at `http://localhost:47331` (backend) and `http://localhost:47332/mcp`
  (MCP server) when `pnpm dev` is active in the OpenAlice directory
- The scanner queries OpenAlice's MCP tools via HTTP — do NOT import OpenAlice TypeScript
  code directly. All communication is over the MCP protocol using the `mcp` Python client
  library (`pip install mcp`)
- OpenAlice MCP tools used:
  - `marketSearchForResearch` — universe discovery
  - `equityGetProfile` — company fundamentals
  - `equityGetFinancials` — financial statements
  - `equityGetRatios` — valuation ratios
  - `calculateIndicator` — technical indicators (RSI, MACD, ATR, BBands, SMA)
  - `globNews` / `grepNews` — news context
  - `equityGetAnalystEstimates` — consensus estimates
  - `equityGetInsiderTrading` — insider flow

### Kronos
- Lives at `../Kronos/` relative to `scanner/`
- The `kronos_service/` FastAPI app imports directly from the Kronos source tree using a
  relative path added to `sys.path`
- Models download to HuggingFace cache on first run (~115 MB for small + tokenizer)
- The service runs on `http://localhost:8765` while scanning
- Default model: `Kronos-small` with `Kronos-Tokenizer-base`. Configurable via `.env`

### Codex API
- Used in `report_generator.py` for synthesis
- Uses `anthropic` Python SDK (`pip install anthropic`)
- Model: `Codex-opus-4-6` (best reasoning for synthesis). Falls back to
  `Codex-sonnet-4-6` if `ANTHROPIC_USE_SONNET=true` in env (cheaper for testing)
- API key from environment: `ANTHROPIC_API_KEY`

---

## Environment Variables

```bash
# .env (copy from .env.example, never commit)

# Required
ANTHROPIC_API_KEY=sk-ant-...

# OpenAlice MCP endpoint (default matches OpenAlice dev server)
OPENALICE_MCP_URL=http://localhost:47332/mcp

# Kronos service (started by scanner automatically)
KRONOS_SERVICE_PORT=8765
KRONOS_MODEL=NeoQuasar/Kronos-small
KRONOS_TOKENIZER=NeoQuasar/Kronos-Tokenizer-base

# Scanner behaviour
DEFAULT_LOOKBACK=400          # candles of history fed to Kronos
DEFAULT_PRED_LEN=20           # candles to forecast (20 daily = ~1 month)
MAX_UNIVERSE_SIZE=500         # cap before fundamental screen
MAX_SCREENED_SIZE=30          # cap before Kronos (inference cost control)
MAX_WATCHLIST_SIZE=10         # names in final output

# Optional
ANTHROPIC_USE_SONNET=false    # true = cheaper, weaker reports
SCANNER_UI_PORT=8080
```

---

## Phase 1 — Core Pipeline (ship this first)

### 1.1 Kronos Service (`kronos_service/`)

Build a FastAPI app that wraps Kronos inference and exposes one endpoint.

**`kronos_service/main.py`**
```python
# FastAPI app
# On startup: load tokenizer + model, log model name and param count
# POST /forecast — accepts ForecastRequest, returns ForecastResponse
# GET /health — returns {"status": "ok", "model": model_name}
```

**`kronos_service/predictor.py`**
```python
# Wraps KronosPredictor
# Handles: OHLCV DataFrame → normalised input → predict() → forecast DataFrame
# Returns: {
#   "symbol": str,
#   "forecast_candles": [...],       # list of {ts, open, high, low, close, volume}
#   "expected_return_pct": float,    # (forecast_close[-1] / current_close - 1) * 100
#   "forecast_high": float,
#   "forecast_low": float,
#   "path_spread_pct": float,        # (high - low) / current_close — uncertainty proxy
# }
```

**Request schema:**
```python
class ForecastRequest(BaseModel):
    symbol: str
    ohlcv: list[dict]      # [{ts, open, high, low, close, volume}, ...]
    pred_len: int = 20
    sample_count: int = 3  # averaged paths — balances speed vs stability
```

**Important:** The service must manage the model in memory (load once, reuse). Do not
reload on every request.

---

### 1.2 OpenAlice MCP Client (`scanner/openalice_client.py`)

Write a thin async client that connects to OpenAlice's MCP server and calls tools.

```python
# Uses: from mcp import ClientSession
# from mcp.client.streamable_http import streamablehttp_client

class OpenAliceClient:
    async def search_symbols(self, query: str, asset_class: str = "equity") -> list[dict]
    async def get_profile(self, symbol: str) -> dict
    async def get_financials(self, symbol: str) -> dict
    async def get_ratios(self, symbol: str) -> dict
    async def get_analyst_estimates(self, symbol: str) -> dict
    async def get_insider_trading(self, symbol: str) -> dict
    async def calculate_indicator(self, asset: str, formula: str) -> dict
    async def get_news(self, query: str, limit: int = 5) -> list[dict]
    async def get_ohlcv(self, symbol: str, interval: str = "1d", bars: int = 450) -> list[dict]
```

Each method should handle MCP tool call failures gracefully — return empty dict/list
rather than raising, and log the failure. Market data is unreliable; the pipeline must
continue if one symbol fails.

---

### 1.3 Universe Builder (`scanner/universe.py`)

```python
class UniverseBuilder:
    async def build(self, directive: str) -> list[str]:
        """
        Takes a user directive (e.g. "European banks", "crypto top 20",
        "semiconductor equipment", or "" for broad sweep).
        
        Returns a list of symbols, capped at MAX_UNIVERSE_SIZE.
        
        Strategy:
        - Parse directive to identify: asset_class, region hint, sector/industry
        - Call marketSearchForResearch with appropriate queries
        - For empty directive: use a curated seed list (S&P500 subset + crypto top 20)
        - Deduplicate, validate symbols exist
        - Return list
        """
```

**Curated seed list for empty directive** (hardcode these as fallback):
- Equities: AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA, JPM, GS, BAC, XOM, CVX,
  JNJ, UNH, PFE, V, MA, WMT, HD, DIS, NFLX, AMD, INTC, QCOM, MU, ASML, SAP,
  NESN, NOVN, ROG, SAN, BNP, AXA, TTE, SHEL, HSBA, LLOY, GSK, AZN, BP
- Crypto: BTCUSD, ETHUSD, SOLUSD, BNBUSD, XRPUSD, ADAUSD, AVAXUSD, DOTUSD

---

### 1.4 Screener (`scanner/screener.py`)

Two-stage filter. Each stage reduces the universe. Both stages run concurrently per
symbol using `asyncio.gather`.

**Fundamental screen** — fetch via OpenAlice, score, threshold:
```python
class FundamentalScreen:
    """
    Scores each symbol 0–100. Passes symbols above threshold (default: 40).
    
    Scoring factors (equity):
    - Revenue growth YoY > 0:           +15 pts
    - Revenue growth YoY > 10%:         +10 pts
    - Positive net income:              +10 pts
    - P/E < sector median (use 25x as proxy): +10 pts
    - Analyst consensus buy/outperform: +20 pts
    - Positive insider net buying:      +10 pts
    - Debt/equity < 2:                  +10 pts
    - Recent earnings beat:             +15 pts
    
    Scoring factors (crypto):
    - 30-day price change > 0:          +25 pts
    - 7-day price change > 0:           +25 pts
    - Volume > 30-day avg volume:       +25 pts  
    - (fundamentals not applicable)     +25 pts (free pass)
    
    Returns: list of (symbol, fund_score) tuples, sorted descending
    """
```

**Technical screen** — calculate indicators via OpenAlice:
```python
class TechnicalScreen:
    """
    Scores each symbol 0–100. Passes symbols above threshold (default: 45).
    
    Indicators calculated:
    - RSI(14): oversold bounce setup (30–50 = +20pts), 
               momentum continuation (50–65 = +15pts)
    - MACD: histogram positive and increasing = +20pts
    - Price vs SMA(50): above = +15pts
    - Price vs SMA(200): above = +10pts  
    - ATR(14): used for stop/target sizing (not scored, passed to report)
    - BBands(20,2): price near lower band = +20pts (mean reversion)
    
    Returns: list of (symbol, tech_score, indicators_dict) tuples
    """
```

Survivors of both screens: take top `MAX_SCREENED_SIZE` by combined score.

---

### 1.5 Kronos Client (`scanner/kronos_client.py`)

```python
class KronosClient:
    """Calls the local Kronos service. Starts the service if not running."""
    
    async def ensure_service_running(self) -> None:
        """
        Checks GET /health. If not responding, starts the service as a subprocess.
        Waits up to 60s for it to become healthy (model load takes time).
        """
    
    async def forecast(self, symbol: str, ohlcv: list[dict]) -> dict | None:
        """
        Calls POST /forecast. Returns forecast dict or None on failure.
        Logs timing — useful for understanding CPU vs GPU speed difference.
        """
```

---

### 1.6 Report Generator (`scanner/report_generator.py`)

The synthesis layer. Takes all collected data for one symbol and generates a structured
report using the Anthropic API.

```python
class ReportGenerator:
    def generate(self, symbol: str, profile: dict, financials: dict, ratios: dict,
                 analyst_estimates: dict, insider_trading: dict, indicators: dict,
                 news: list[dict], forecast: dict, fund_score: float,
                 tech_score: float) -> dict:
        """
        Calls Codex with a structured prompt and parses the response into:
        {
            "symbol": str,
            "name": str,
            "conviction": int,          # 1-5, Codex's own assessment
            "thesis": str,              # 1-2 paragraphs, plain prose
            "fundamental_summary": str, # 3-5 sentences
            "technical_summary": str,   # 3-5 sentences  
            "forecast_summary": str,    # what Kronos says, in plain language
            "entry_zone": str,          # e.g. "$187–191"
            "stop_loss": str,           # e.g. "$182 (ATR-based)"
            "target": str,              # e.g. "$204 (forecast high)"
            "risk_reward": str,         # e.g. "1:2.8"
            "timeframe": str,           # e.g. "2–4 weeks"
            "strategy_type": str,       # "momentum" | "mean_reversion" | "breakout" | "value"
            "risks": list[str],         # 2-4 bullet risks
            "tags": list[str],          # e.g. ["tech", "large_cap", "earnings_play"]
        }
        """
```

**System prompt for Codex (use this exactly):**

```
You are a rigorous financial analyst producing investment research for a sophisticated
individual investor. Your reports are precise, honest, and free of promotional language.

You will receive structured data for a single security: fundamentals, technicals, a
Kronos model price forecast, and recent news. Generate a research report in JSON format.

Rules:
- Conviction score 1–5: only give 4–5 if the evidence is genuinely strong across
  multiple dimensions. 3 is the honest average. Be calibrated, not generous.
- The thesis must be YOUR synthesis — do not summarise the data. Say what it means.
- Entry/stop/target must be specific numbers derived from the ATR and forecast range.
  Do not give vague ranges like "near current price".
- Risks must be specific to this name — not generic market risks.
- If the data is insufficient to form a view, say so in the thesis and give conviction 1.
- No em dashes. No exclamation marks. No corporate clichés.
- Output valid JSON only — no preamble, no markdown fences.
```

---

### 1.7 Output Serialiser (`scanner/output.py`)

```python
class WatchlistOutput:
    def build(self, reports: list[dict]) -> dict:
        """
        Assembles final watchlist:
        {
            "generated_at": ISO timestamp,
            "directive": str,
            "total_scanned": int,
            "total_screened": int,
            "watchlist": [
                {
                    "rank": int,
                    "symbol": str,
                    "name": str,
                    "conviction": int,
                    "strategy_type": str,
                    "expected_return_pct": float,  # from Kronos
                    "risk_reward": str,
                    "timeframe": str,
                    "tags": list[str],
                    "report": { ...full report dict... }
                }
            ]
        }
        
        Sorted by: conviction DESC, then expected_return_pct DESC.
        Capped at MAX_WATCHLIST_SIZE.
        """
    
    def save(self, watchlist: dict, path: str) -> None:
        """Save as JSON to outputs/ directory with timestamp in filename."""
    
    def to_markdown(self, watchlist: dict) -> str:
        """Plain markdown summary for quick reading — one section per name."""
```

---

### 1.8 CLI Entry Point (`scanner/run.py`)

```python
# Usage:
#   python -m scanner.run "European banks"
#   python -m scanner.run "semiconductor equipment" --max-results 5
#   python -m scanner.run "" --asset-class crypto
#   python -m scanner.run --from-file symbols.txt

# Steps:
# 1. Parse args
# 2. Load config from .env
# 3. Check OpenAlice is reachable (GET health check on MCP endpoint)
# 4. Start Kronos service if not running
# 5. Run pipeline: universe → screen → forecast → report → output
# 6. Save JSON to outputs/
# 7. Start UI server pointing at latest output
# 8. Open browser to localhost:8080

# Progress reporting: print a clear status line for each stage
# e.g.: "[1/5] Building universe for 'European banks'..."
#       "[2/5] Fundamental screen: 47 candidates..."
#       "[3/5] Technical screen: 18 survivors..."
#       "[4/5] Kronos forecasting: 12 names (this takes ~2min on CPU)..."
#       "[5/5] Generating reports..."
#       "Done. Watchlist: 8 names. Opening UI..."
```

---

## Phase 2 — UI (`ui/`)

Plain HTML/CSS/JS. No React, no build step. Opens directly from file or served by a
one-line Python HTTP server. Reads the JSON output file.

**Design direction:** Financial terminal aesthetic. Dark background (#0a0a0f),
monospace accents, clean data tables, no decorative chrome. Think Bloomberg without
the licensing fee. Fonts: JetBrains Mono for data, IBM Plex Sans for prose.

**Layout:**

```
┌─────────────────────────────────────────────────┐
│  SCANNER  │  directive  │  timestamp  │  stats  │
├─────────────────────────────────────────────────┤
│  WATCHLIST (left panel, ~35%)                   │
│  ┌─────────────────────────────────────────┐    │
│  │ #1  AAPL  ★★★★☆  momentum  +8.3%  1:2.4│    │
│  │ #2  NVDA  ★★★★★  breakout  +12.1% 1:3.1│    │
│  │  ...                                    │    │
│  └─────────────────────────────────────────┘    │
│                                                 │
│  REPORT (right panel, ~65%)                     │
│  ┌─────────────────────────────────────────┐    │
│  │ AAPL — Apple Inc.          [MOMENTUM]   │    │
│  │                                         │    │
│  │ THESIS                                  │    │
│  │ [thesis prose]                          │    │
│  │                                         │    │
│  │ FUNDAMENTALS  │  TECHNICALS  │ FORECAST │    │
│  │ [summaries]   │  [summaries] │ [chart]  │    │
│  │                                         │    │
│  │ STRATEGY                                │    │
│  │ Entry: $187–191  Stop: $182  Target:$204│    │
│  │ R/R: 1:2.8   Timeframe: 2–4 weeks      │    │
│  │                                         │    │
│  │ RISKS                                   │    │
│  │ • [risk 1]                              │    │
│  │ • [risk 2]                              │    │
│  └─────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

The forecast section shows a simple SVG sparkline of the Kronos predicted candles
(just close prices — no need for full candlestick rendering in v1).

Clicking a watchlist entry loads its report in the right panel instantly (pure JS, no
network call — data is already in the page).

**`ui/index.html`** — single-file app. Inlines the CSS and JS for portability.
Accepts a `?data=` query param pointing at a JSON file, or auto-loads the most recent
file in `outputs/`.

---

## Phase 3 — Automation (add after Phase 1 and 2 are stable)

### 3.1 Scheduled Scan

Add a simple scheduler using Python's `schedule` library:

```python
# scanner/scheduler.py
# Runs a configured scan on a cron-like schedule
# e.g.: every weekday at 7:00 AM before market open
# Saves output to outputs/ and optionally sends a summary to OpenAlice inbox
```

### 3.2 OpenAlice Inbox Integration

When a scan completes, optionally push a summary to the OpenAlice workspace inbox:

```python
# Call POST http://localhost:47331/api/events/ingest with:
# {
#   "type": "scanner.complete",
#   "payload": {
#     "directive": str,
#     "watchlist_summary": "Top picks: NVDA (★★★★★, +12%), AAPL (★★★★☆, +8%)...",
#     "output_path": str
#   }
# }
```

This means OpenAlice sees scanner output as an event and can reference it in chat.

---

## Error Handling Contract

Every external call (OpenAlice MCP, Kronos service, Anthropic API) must:
1. Catch all exceptions
2. Log the failure with symbol and error message
3. Return a sensible empty/null value — never raise to the pipeline
4. The pipeline skips symbols that fail data fetch; it never aborts

The only acceptable abort conditions:
- OpenAlice MCP is unreachable at startup
- Anthropic API key is missing or invalid
- Kronos service fails to start after 60s

---

## Testing

### Unit tests (`tests/`)
- `test_screener.py`: mock OpenAlice responses, verify scoring logic
- `test_kronos_client.py`: mock the service, verify request formatting
- `test_output.py`: given a list of mock reports, verify sorting and serialisation

### Integration test (`tests/test_integration.py`)
- Requires live OpenAlice + Kronos service
- Runs a scan for `["AAPL", "MSFT"]` (hardcoded, bypasses universe building)
- Asserts: report dict has all required keys, conviction is 1–5, JSON is valid

Run with: `pytest tests/ -v`
Integration test only: `pytest tests/test_integration.py -v --integration`

---

## Build Order for Codex

Execute phases strictly in this order. Do not skip ahead.

**Session 1:**
1. Create repo structure (all directories, empty `__init__.py` files, `.gitignore`,
   `.env.example`, `requirements.txt`, `pyproject.toml`)
2. Write `kronos_service/predictor.py` and `kronos_service/main.py`
3. Test Kronos service: `uvicorn kronos_service.main:app --port 8765`
   Verify: `curl http://localhost:8765/health` returns ok

**Session 2:**
4. Write `scanner/config.py` (loads .env, validates required vars)
5. Write `scanner/openalice_client.py`
6. Test: connect to live OpenAlice, call `marketSearchForResearch("AAPL")`, print result

**Session 3:**
7. Write `scanner/universe.py`
8. Write `scanner/screener.py`
9. Test: run screener against 5 hardcoded symbols, print scores

**Session 4:**
10. Write `scanner/kronos_client.py`
11. Write `scanner/report_generator.py`
12. Test: single symbol end-to-end, print report JSON

**Session 5:**
13. Write `scanner/output.py`
14. Write `scanner/run.py`
15. Run full pipeline: `python -m scanner.run "AAPL MSFT NVDA"` (symbol list mode)
16. Fix anything broken

**Session 6:**
17. Build `ui/index.html` with full layout
18. Wire to output JSON
19. Test: open browser, verify watchlist and report display correctly

**Session 7:**
20. Write all unit tests
21. Run `pytest tests/` — fix failures
22. Write `README.md` with setup instructions

**Session 8+ (Phase 3):**
23. Add scheduler
24. Add OpenAlice inbox integration
25. Polish UI with forecast sparkline

---

## Requirements File

```
# requirements.txt

# Core
fastapi==0.115.0
uvicorn[standard]==0.30.0
httpx==0.27.0
pydantic==2.8.0
python-dotenv==1.0.0

# Kronos dependencies (defer to Kronos/requirements.txt for torch version)
torch
numpy
pandas
transformers

# OpenAlice MCP client
mcp==1.0.0

# Anthropic
anthropic>=0.34.0

# Scanner utilities
schedule==1.2.0
rich==13.7.0          # pretty terminal output

# Testing
pytest==8.3.0
pytest-asyncio==0.23.0
```

Note on PyTorch: do not pin the version here. Let the user's existing Kronos environment
carry it. If the user has no existing environment, install CPU torch:
`pip install torch --index-url https://download.pytorch.org/whl/cpu`

---

## Key Decisions Recorded Here

**Why not use OpenAlice workspaces for the scanner?**
OpenAlice workspaces are Codex sessions attached to the OpenAlice runtime.
The scanner is an independent Python application that *calls* OpenAlice as a data source.
Using the workspace system would mean the scanner lives inside OpenAlice's file tree and
terminal management — that's coupling we don't want. Keep them separate.

**Why FastAPI for Kronos instead of calling it directly?**
Kronos loads a ~100MB model. If called directly from the scanner process, that model is
loaded and unloaded on every scan. The FastAPI service loads once and stays warm.
It also cleanly separates Python environments if needed.

**Why plain HTML/CSS/JS for the UI?**
No build step. No Node dependency (OpenAlice already has one; don't add another).
The UI opens from any file manager or serves in one command. Fast to build and modify.

**Why Codex for synthesis rather than a rules engine?**
The report requires genuine reasoning across heterogeneous data — fundamentals,
technicals, a price forecast, and news. Rules engines produce formulaic output.
Codex produces the "why this name, why now" narrative that makes the watchlist
actually useful.

**Why cap Kronos at MAX_SCREENED_SIZE names?**
CPU inference: ~30–60 seconds per symbol. 30 symbols = 15–30 minutes, which is
acceptable for a scheduled morning scan. More than that crosses into impractical
on consumer hardware.

---

## Definition of Done

The scanner is shippable when:
- [ ] `python -m scanner.run "European financials"` completes without error
- [ ] Output JSON is valid and contains at least 3 watchlist entries
- [ ] UI renders the watchlist and report correctly in a browser
- [ ] All unit tests pass
- [ ] `README.md` explains setup in under 10 steps

---

*End of specification.*
