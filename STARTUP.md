# Vigil — Startup, Shutdown & Usage

Everything to run Vigil day to day. **The fastest first live test needs nothing
but this repo** (no OpenAlice) — see §1.

## 0. One-time setup
```bash
pip install -r requirements.txt
# Kronos must be cloned as a sibling at ~/Kronos:
#   git clone https://github.com/shiyu-coder/Kronos.git ~/Kronos
#   pip install -r ~/Kronos/requirements.txt
```
Your `.env` is already filled in (Gemini key + sensible defaults).

## 1. FASTEST live test (no OpenAlice, small universe)  ⭐
Uses the free Yahoo data fallback — needs only Python + Kronos.
```bash
python -m scanner.run "AAPL MSFT NVDA" --offline --provider none --no-ui
```
First run downloads the Kronos model (~115 MB) once. Output -> outputs/latest.json.
Crypto: `python -m scanner.run "" --asset-class crypto --offline`.
Index scans now expand into component companies, so they are intentionally larger.

## 2. START the app (browser control panel)
Double-click **Vigil.command**, or:
```bash
python -m scanner.server          # opens http://127.0.0.1:8080
```
- Section nav: one-click World/US/Europe/Asia/Crypto scans + **My portfolio**.
- Directive box + **RUN SCAN**; asset toggle Auto/Equity/Crypto.
- Gear: Send Telegram signal | Push to Inbox | Stage orders | Max results.
- History dropdown; clock icon = calibration.
- Watchlist filters by **trading horizon**: Low (day-trade-like) / Med / High (long-term).
- Report has Thesis, **Why now** (reasons), **Performance** (1M/3M/1Y, vol, drawdown,
  52w range, SMA distances), Forecast fan chart, Strategy, Risks.
- **+ Portfolio** button on any report adds it to your local portfolio.
- **Send to Alice** pushes only the selected report into OpenAlice Inbox for
  follow-up, without sending the whole watchlist.
Masthead LEDs show OpenAlice/Kronos reachability (red OpenAlice is fine for index/crypto).

## 3. START everything together (OpenAlice + Vigil + on-demand Kronos)
For the full equity workflow, double-click **Vigil Full Stack.command**.

It starts:
- **OpenAlice** from `OPENALICE_DIR` (default `~/OpenAlice`) with `pnpm dev`.
- **Vigil** on `SCANNER_UI_PORT` (default `8080`) and opens the browser.
- **Kronos on demand**: by default it is *not* pre-warmed, so opening the app
  does not heat the machine. The first scan that needs forecasting starts it.

Logs are written to `logs/openalice.log`, `logs/kronos.log`, and `logs/vigil.log`.
The launcher truncates those logs at startup so they do not grow forever.
Close that Terminal window, or press Ctrl-C, to stop only the processes the
launcher started. If you already had OpenAlice or Kronos running, the launcher
will reuse them and leave them alone.

Launcher knobs in `.env`:
```bash
VIGIL_START_OPENALICE=true   # false = do not start OpenAlice, just probe it
VIGIL_WARM_KRONOS=false      # true = load Kronos immediately at startup
```

## 4. Portfolio & sell warnings
1. Run a scan, open a pick, click **+ Portfolio**.
2. Click **My portfolio** -> see holdings, remove, or **Check for sell signals**
   (forecasts each holding, warns on negatives).
3. Holdings are auto-checked every scan (shown HELD; negatives appear under Exit
   signals). Stored in portfolio.json.

## 5. Full power manually (with OpenAlice — equity fundamentals, news, positions)
Only needed for equity fundamentals/news/macro/earnings/broker positions/Inbox/staging.
```bash
cd ~/OpenAlice && pnpm install && pnpm build && pnpm dev   # leave running
# set OPENALICE_MCP_URL in .env to the MCP port it prints
```
Index scans use ETF benchmarks (`SPY`, `QQQ`, `DIA`) but screen/report the
underlying component companies as equity ideas.
Local safety cap: `MAX_INDEX_COMPONENTS_LOCAL=120` before screening, then
`MAX_SCREENED_SIZE=30` before Kronos/report generation. Full every-component
processing should be run through remote/offloaded processing.

## 6. Telegram signals (iPhone)
1. Telegram @BotFather -> /newbot -> copy token.
2. Message the bot once; open https://api.telegram.org/bot<TOKEN>/getUpdates -> chat id.
3. .env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SIGNAL_MARKETS=us,crypto,portfolio
4. Test: `python -m scanner.signals`
24/7 free: push to GitHub, add the two secrets + repo var SIGNAL_MARKETS;
.github/workflows/vigil-signals.yml runs daily and texts you.

## 7. Offload forecasting off this Mac (optional)
Run the Kronos service on any always-on box and set in .env:
`KRONOS_SERVICE_URL=http://that-host:8765`  (Vigil uses it instead of a local one.)

## 8. SHUTDOWN
- Simple app: close the Terminal window Vigil.command opened, or Ctrl-C the server.
- Full stack: close the Terminal window Vigil Full Stack.command opened, or Ctrl-C it.
- Stray Kronos: `pkill -f "uvicorn kronos_service"`
- OpenAlice started manually: Ctrl-C its pnpm dev terminal.
Nothing runs in the background after that. Outputs in outputs/, portfolio in portfolio.json.

## 9. Cheat-sheet
```bash
python -m scanner.server                    # the app
python -m scanner.run "<directive>" [flags] # one scan
python -m scanner.signals [markets...]      # market + portfolio signals
python -m scanner.calibrate                 # score past forecasts
pytest tests/ -q                            # tests
# flags: --asset-class equity|crypto|index  --offline  --provider gemini|anthropic|none
#        --no-ui  --notify/--no-notify  --push-inbox  --stage-orders  --max-results N
```
