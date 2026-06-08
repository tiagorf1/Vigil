# Vigil — Cloud Processing & Phone Control

Goal: run the heavy, most-accurate compute OFF your Mac, and drive it from your
phone via Telegram. Three tiers — pick by budget.

## What "more accurate" costs (the compute levers)
- Kronos-**base** instead of -small  (set `KRONOS_MODEL=NeoQuasar/Kronos-base`)
- more Monte-Carlo paths  (`KRONOS_MC_PATHS=64+`)
- bigger universe / full index components
- ensembles + walk-forward calibration
These need a real box; that's the whole point of going to the cloud.

## Tier 1 — Free, always-on: Oracle Cloud Always-Free ARM (recommended backbone)
4 cores / 24 GB, $0 forever. Runs Kronos (CPU), the worker, and the Telegram bot.
```bash
# on the VM
git clone <your Vigil repo> && cd Vigil
git clone https://github.com/shiyu-coder/Kronos.git ~/Kronos
pip install -r requirements.txt -r ~/Kronos/requirements.txt
cp .env.example .env   # set GEMINI/TELEGRAM keys, KRONOS_DEVICE=cpu
# interactive phone control:
python -m scanner.telegram_bot        # text /scan us, /deep NVDA, /portfolio
# or scheduled signals via cron:
#   0 12 * * 1-5  cd ~/Vigil && python -m scanner.signals
```

## Tier 2 — Free, scheduled: GitHub Actions (already wired)
`.github/workflows/vigil-signals.yml` runs `python -m scanner.signals` on cron and
Telegrams you. Add repo secrets `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, optional
`GEMINI_API_KEY`, and a repo variable `SIGNAL_MARKETS`. Good for daily pushes; no GPU.

## Tier 3 — Cheap burst GPU for deep scans: RunPod / Vast.ai / Modal
Rent a spot GPU only when you want a full, high-accuracy run, then stop it.
```bash
# on the GPU box
pip install -r requirements.txt -r ~/Kronos/requirements.txt
KRONOS_MODEL=NeoQuasar/Kronos-base KRONOS_MC_PATHS=64 python -m scanner.worker
# from your Mac / bot, point at it:
#   KRONOS_SERVICE_URL=http://<gpu-host>:8765   (remote Kronos)
# or submit a job to the worker API: POST /jobs {directive, asset_class, ...}
```
Idle cost ~$0 (box is off); a deep run is cents. Never keep a GPU always-on unless
the signal value justifies it.

## Split brain (best of both)
- Mac / Oracle-Free: orchestration, UI, scheduled signals, Telegram bot.
- Spot GPU (on demand): `scanner.worker` for the occasional full-universe deep scan.
- Wire them with `KRONOS_SERVICE_URL` (remote forecaster) — one env var.

## Phone control (cloud → Telegram)
Run `python -m scanner.telegram_bot` on the always-on box. From your phone:
```
/scan us            /scan crypto       /scan global-liquid
/deep AAPL MSFT     /portfolio         /signals     /status
```
Only your `TELEGRAM_CHAT_ID` is honored. The box does the compute; you get the signal.
