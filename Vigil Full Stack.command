#!/bin/bash
# Double-click this file (macOS) to launch the Vigil stack:
# OpenAlice + Vigil control panel. Kronos starts on demand by default.
#
# Close this Terminal window or press Ctrl-C to stop the processes this script
# started. Existing services that were already running are left alone.

set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

ENV_FILE="$ROOT/.env"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

OPENALICE_DIR="${OPENALICE_DIR:-$HOME/OpenAlice}"
OPENALICE_MCP_URL="${OPENALICE_MCP_URL:-http://localhost:47332/mcp}"
KRONOS_SERVICE_PORT="${KRONOS_SERVICE_PORT:-8765}"
SCANNER_UI_PORT="${SCANNER_UI_PORT:-8080}"
VIGIL_START_OPENALICE="${VIGIL_START_OPENALICE:-true}"
VIGIL_WARM_KRONOS="${VIGIL_WARM_KRONOS:-false}"

OPENALICE_PID=""
KRONOS_PID=""
VIGIL_PID=""

is_reachable() {
  curl -sS -o /dev/null --max-time 2 "$1" >/dev/null 2>&1
}

cleanup() {
  echo
  echo "Stopping Vigil stack processes started by this launcher..."
  if [ -n "$VIGIL_PID" ]; then kill "$VIGIL_PID" >/dev/null 2>&1 || true; fi
  if [ -n "$KRONOS_PID" ]; then kill "$KRONOS_PID" >/dev/null 2>&1 || true; fi
  if [ -n "$OPENALICE_PID" ]; then kill "$OPENALICE_PID" >/dev/null 2>&1 || true; fi
  wait >/dev/null 2>&1 || true
  echo "Done."
}
trap cleanup EXIT INT TERM

echo "Starting Vigil full stack..."
echo "Project: $ROOT"
echo "Logs:    $LOG_DIR"
echo

: >"$LOG_DIR/openalice.log"
: >"$LOG_DIR/kronos.log"
: >"$LOG_DIR/vigil.log"

if [ "$VIGIL_START_OPENALICE" != "true" ]; then
  echo "Skipping OpenAlice startup (VIGIL_START_OPENALICE=$VIGIL_START_OPENALICE)."
elif is_reachable "$OPENALICE_MCP_URL"; then
  echo "OpenAlice already reachable at $OPENALICE_MCP_URL"
else
  if [ ! -d "$OPENALICE_DIR" ]; then
    echo "OpenAlice folder not found: $OPENALICE_DIR"
    echo "Set OPENALICE_DIR in .env if your clone lives somewhere else."
    exit 1
  fi
  if ! command -v pnpm >/dev/null 2>&1; then
    echo "pnpm is not available. Run: corepack enable pnpm"
    exit 1
  fi
  echo "Starting OpenAlice from $OPENALICE_DIR ..."
  (
    cd "$OPENALICE_DIR" || exit 1
    pnpm dev
  ) >"$LOG_DIR/openalice.log" 2>&1 &
  OPENALICE_PID=$!
  echo "OpenAlice log: $LOG_DIR/openalice.log"
fi

KRONOS_HEALTH="http://127.0.0.1:$KRONOS_SERVICE_PORT/health"
if [ "$VIGIL_WARM_KRONOS" != "true" ]; then
  echo "Kronos warm-start skipped (VIGIL_WARM_KRONOS=false)."
  echo "Vigil will start Kronos automatically on the first forecast."
elif is_reachable "$KRONOS_HEALTH"; then
  echo "Kronos already reachable at $KRONOS_HEALTH"
else
  echo "Starting Kronos service on port $KRONOS_SERVICE_PORT ..."
  python3 -m uvicorn kronos_service.main:app \
    --port "$KRONOS_SERVICE_PORT" \
    --log-level warning \
    >"$LOG_DIR/kronos.log" 2>&1 &
  KRONOS_PID=$!
  echo "Kronos log: $LOG_DIR/kronos.log"
fi

echo "Starting Vigil control panel on http://127.0.0.1:$SCANNER_UI_PORT ..."
python3 -m scanner.server >"$LOG_DIR/vigil.log" 2>&1 &
VIGIL_PID=$!
echo "Vigil log: $LOG_DIR/vigil.log"
echo
echo "Vigil will open the browser automatically."
echo "Tip: set VIGIL_WARM_KRONOS=true in .env if you prefer model warm-up at launch."
echo "Keep this window open while you use Vigil."

wait "$VIGIL_PID"
