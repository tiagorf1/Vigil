# Vigil Processing Routes

Priorities:
1. Simple startup/running.
2. Low disk usage.
3. Low heat / low slowdown on the Mac.

The right shape is: keep **Vigil** as the local app/cockpit, keep **OpenAlice**
as the local data/workspace bridge, and move heavy **Kronos** work off-machine
when scans become large.

## Recommended Path

## Free / Dirt-Cheap Execution Plan

Start with the fully free version, then only pay when a scan is too large:

1. **Free scheduled signals:** use the existing GitHub Actions workflow
   (`.github/workflows/vigil-signals.yml`) to run offline scheduled scans and send
   Telegram messages. Keep the default profile liquid and brokerage-friendly:
   `global-liquid`.
2. **Free local deep scans:** use the Vigil UI for deliberate manual scans. Increase
   forecast days and MC paths only when the universe is small enough to justify the
   compute; the app warns when local forecast load enters heat/slowdown territory.
3. **Free/cheap remote Kronos:** when the Mac gets hot, point `KRONOS_SERVICE_URL`
   at a remote machine. Oracle Cloud Always Free ARM is the best no-cost always-on
   candidate if setup succeeds; otherwise a tiny VPS handles orchestration and a
   spot GPU handles only deep jobs.
4. **Paid only for full components:** for full S&P/Nasdaq component runs, rent a
   RunPod/Vast.ai spot GPU, start `python -m scanner.worker`, run the job, then stop
   it. This keeps cost near zero when idle and avoids storing duplicate model
   weights on your Mac.

The important rule: **do not keep a GPU box always on** unless the signal value
justifies it. Scheduled narrow scans are free; full-index deep scans are occasional
jobs.

### Route A — Local app, remote Kronos
Best first step.

- Vigil and OpenAlice run locally.
- Kronos runs on a remote GPU/CPU box.
- Set one env var locally:

```bash
KRONOS_SERVICE_URL=http://remote-host:8765
```

Pros:
- Minimal code change, already supported.
- No model heat/load on this Mac.
- No duplicate data or repo storage locally.
- The UI stays exactly the same.

Cons:
- Remote machine must be reachable.
- You still screen/fetch data locally unless we later move the whole scan worker.

### Route B — Cloud scheduled scans
Good for daily signals.

- GitHub Actions or a small VPS runs `python -m scanner.signals`.
- Results can Telegram you and/or push into OpenAlice Inbox.
- Local app remains for reading and manual scans.

Pros:
- Free/cheap.
- No always-on Mac.
- Great for morning scans.

Cons:
- GitHub-hosted CPU is slow for full Kronos.
- Better for narrowed universes unless paired with remote Kronos.

Current workflow:
- `.github/workflows/vigil-signals.yml`
- Runs multiple times per weekday and twice on weekends.
- Default markets: `us,commodities,forex,crypto`.
- Needs GitHub Actions secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

### Route C — Full remote scan worker
Best longer-term app architecture.

- Local Vigil UI sends a job to a remote worker.
- Worker runs universe -> screen -> Kronos -> reports.
- Local app polls job status and downloads the output JSON.

Pros:
- Mac stays cool.
- Enables full S&P 500 / Nasdaq 100 component scans.
- Can run multiple jobs or scheduled jobs.

Cons:
- Needs a small job API, storage bucket or file sync, and auth.
- More moving parts than Route A.

Minimal implementation shape:

```text
Local Vigil UI
  POST /api/remote-scan
      -> remote worker /jobs

Remote worker
  POST /jobs              create queued job
  GET  /jobs/{id}         status: queued | screening | forecasting | reporting | done | error
  GET  /jobs/{id}/result  final watchlist JSON

Local Vigil UI
  polls job status
  downloads final JSON
  saves outputs/remote_<id>.json and latest.json
```

The remote worker should run the same Python package, but with:

```bash
MAX_INDEX_COMPONENTS_LOCAL=0
MAX_SCREENED_SIZE=100       # or higher, depending on hardware
KRONOS_SERVICE_URL=http://127.0.0.1:8765
```

First worker version is scaffolded in `scanner/worker.py`:

```bash
python -m scanner.worker
```

It runs one job at a time:

```bash
curl -X POST http://remote-host:8090/jobs \
  -H 'Content-Type: application/json' \
  -d '{"directive":"s&p 500","asset_class":"index","full_index":true,"max_screened_size":100}'
```

Then poll `/jobs/{job_id}` and fetch `/jobs/{job_id}/result`.

### Route D — Queue-based workers
Best if you want many markets or multiple machines.

- Vigil pushes scan jobs into a queue.
- One or more workers pick jobs up.
- Results return to a shared output store.

Pros:
- Scales cleanly.
- Lets you split index components into chunks.

Cons:
- More infrastructure. Overkill until full-index scans are routine.

## Index Scan Semantics

Index scans should not mean "analyze the direction of ^GSPC." They should mean:

- Use liquid tradeable ETF handles as benchmark context:
  - S&P 500 -> `SPY`
  - Nasdaq 100 -> `QQQ`
  - Dow 30 -> `DIA`
- For broad S&P/US index scans, also forecast sector sleeve ETFs (`XLK`,
  `XLF`, `XLV`, `XLE`, `XLY`, `XLP`, `XLI`, `XLB`, `XLU`, `XLRE`, `XLC`) as
  market context and, later, as a remote-worker prefilter.
- Expand the index into component companies.
- Screen/report the companies as equity ideas.
- Store ETF forecasts under `benchmarks`, not in the company watchlist.

Current local behavior:
- `--asset-class index` expands to component companies.
- Companies are screened as equities.
- ETF forecasts are benchmark context.
- Local runs apply `MAX_INDEX_COMPONENTS_LOCAL` before screening, then
  `MAX_SCREENED_SIZE` before forecasting/reporting.
- Default local safety: `MAX_INDEX_COMPONENTS_LOCAL=120`, `MAX_SCREENED_SIZE=30`.

Needed for true "every component gets a forecast/report":
- Route A at minimum, preferably Route C.
- Set local caps only when remote capacity is available, or run a remote worker
  that chunks the full universe.
- Add a full-index mode that chunks component lists and runs all batches remotely.
- Add an output view with three levels:
  1. Benchmark ETF forecast.
  2. Full component table.
  3. Ranked investment ideas.

## Disk Discipline

- Logs are truncated by `Vigil Full Stack.command` on startup.
- Component lists are cached weekly in `.cache/index_components`.
- Outputs are JSON files in `outputs/`; add pruning before heavy remote scans.
- Avoid storing model weights in this repo. Kronos/HuggingFace cache should stay
  outside the project folder.

## Low-Heat Discipline

- `VIGIL_WARM_KRONOS=false` by default.
- Local Kronos starts only when a forecast is needed.
- Remote Kronos is preferred for full component scans.
- Keep local watchlist/report cap conservative unless a remote worker is active.

## Integration / Owning the Code

It is possible to reconstruct the useful pieces into this folder, but there are
two different meanings:

1. **Single app shell**: recommended now. Vigil owns the UI, launchers,
   scan orchestration, outputs, Telegram, workers, and settings. OpenAlice and
   Kronos are treated as replaceable service backends.
2. **Vendored/rebuilt internals**: possible later. Copy or reimplement the
   specific OpenAlice data adapters and Kronos inference code into Vigil, then
   remove the external folders.

Why not do (2) immediately:
- Kronos has model-loading and dependency complexity; copying it can increase
  disk use and break updates.
- OpenAlice has many tools; Vigil only needs a subset. Rebuilding that subset
  cleanly is better than copying the whole app.
- Keeping services separate makes remote workers easier.

Best route toward ownership:
- First define the exact APIs Vigil needs.
- Then replace one backend at a time:
  - OpenAlice market data -> Vigil data adapters.
  - OpenAlice Inbox/staging -> optional local note/order-staging module.
  - Kronos service -> vendored `vigil_forecast` module or remote worker image.
