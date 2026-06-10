#!/bin/bash
# Double-click to launch the Vigil cockpit. Opens the browser automatically.
PY="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3)"
cd "$(dirname "$0")" || exit 1
echo "Starting Vigil… browser opens shortly. Close this window to stop."
exec "$PY" -m scanner.server
