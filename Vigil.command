#!/bin/bash
# Double-click this file (macOS) to launch the Vigil control panel.
# It starts the local server and opens the browser; close the Terminal window to stop.
cd "$(dirname "$0")"
echo "Starting Vigil — Markets Watch…"
echo "Your browser will open automatically. Close this window to stop the server."
echo
exec python3 -m scanner.server
