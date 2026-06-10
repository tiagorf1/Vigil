#!/usr/bin/env bash
# One-command honest backtest on a RunPod GPU pod. No typing a symbol wall.
# Usage on the pod:   bash deploy/pod-backtest.sh            (default 12 cuts)
#                     bash deploy/pod-backtest.sh 20         (heavier: 20 cuts)
# Watch:  tail -f ~/bt.log     Results when done:  tail -90 ~/bt.log
set -euo pipefail
cd "$(dirname "$0")/.."

export KRONOS_REPO_PATH="${KRONOS_REPO_PATH:-/workspace/Kronos}"
export KRONOS_MODEL="${KRONOS_MODEL:-NeoQuasar/Kronos-base}"
export KRONOS_TOKENIZER="${KRONOS_TOKENIZER:-NeoQuasar/Kronos-Tokenizer-base}"
export KRONOS_DEVICE="${KRONOS_DEVICE:-cuda}"
export HF_HUB_ENABLE_HF_TRANSFER=0

CUTS="${1:-12}"
EQUITY="AAPL MSFT NVDA AMZN GOOGL META JPM V JNJ WMT PG XOM CVX HD KO MRK ABBV BAC DIS CSCO INTC AMD QCOM CRM NFLX MCD NKE BA CAT UNH PFE LLY TSLA ORCL IBM GS"
CRYPTO="BTCUSD ETHUSD SOLUSD BNBUSD XRPUSD ADAUSD AVAXUSD DOTUSD LINKUSD DOGEUSD"
FX="EURUSD=X GBPUSD=X USDJPY=X USDCHF=X AUDUSD=X USDCAD=X"
COMMOD="GLD SLV USO UNG CPER DBA"

nohup python -m scanner.backtest --cuts "$CUTS" --horizons 10 30 60 --paths 24 \
  --symbols $EQUITY $CRYPTO $FX $COMMOD > ~/bt.log 2>&1 &
echo "Backtest started (PID $!), cuts=$CUTS, 58 symbols across equity/crypto/FX/commodity."
echo "Watch:    tail -f ~/bt.log"
echo "Status:   bash deploy/pod-status.sh"
echo "Results:  tail -90 ~/bt.log   (after it finishes)"
