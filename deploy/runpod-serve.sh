#!/usr/bin/env bash
# Launch the Kronos forecasting service on a RunPod GPU pod, bound so the
# RunPod HTTP proxy can reach it. Run this ONCE on the pod (or set it as the
# pod's start command). Then drive backtests/scans from your Mac or the Oracle
# box by pointing KRONOS_SERVICE_URL at the pod's proxy URL — no web terminal.
#
# Setup on a fresh pod (PyTorch template):
#   cd /workspace && git clone https://github.com/tiagorf1/Vigil.git \
#     && git clone https://github.com/shiyu-coder/Kronos.git
#   cd Vigil && pip install -r requirements.txt && pip install -r /workspace/Kronos/requirements.txt
#   bash deploy/runpod-serve.sh
#
# In the RunPod pod config, expose HTTP port 8765. RunPod gives you a URL like
#   https://<POD_ID>-8765.proxy.runpod.net
# On your Mac (or box), point Vigil at it and run normally:
#   export KRONOS_SERVICE_URL=https://<POD_ID>-8765.proxy.runpod.net
#   python -m scanner.backtest --cuts 16 --horizons 10 30 60 --paths 24 --symbols AAPL MSFT ...
#   # or a full scan:  python -m scanner.run "sp500" --asset-class index --offline --no-ui
set -euo pipefail

cd "$(dirname "$0")/.."

export KRONOS_REPO_PATH="${KRONOS_REPO_PATH:-/workspace/Kronos}"
export KRONOS_MODEL="${KRONOS_MODEL:-NeoQuasar/Kronos-base}"
export KRONOS_TOKENIZER="${KRONOS_TOKENIZER:-NeoQuasar/Kronos-Tokenizer-base}"
export KRONOS_DEVICE="${KRONOS_DEVICE:-cuda}"
export HF_HUB_ENABLE_HF_TRANSFER=0          # avoid the hf_transfer dependency error

PORT="${KRONOS_SERVICE_PORT:-8765}"
echo "Starting Kronos service on 0.0.0.0:${PORT} (device=${KRONOS_DEVICE}, model=${KRONOS_MODEL})"
echo "Expose HTTP port ${PORT} in RunPod, then set KRONOS_SERVICE_URL to the proxy URL on your Mac."
exec uvicorn kronos_service.main:app --host 0.0.0.0 --port "${PORT}"
