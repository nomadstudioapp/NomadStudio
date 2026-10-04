#!/usr/bin/env bash
# Nomad Studio launcher for the macOS portable build (docs/APP_UPDATES.md §7.4).
# A .command file opens in Terminal on double-click. Lives at the root of the
# NomadStudio folder, next to app/. Starts the bundled Python; the app itself
# opens the browser once it answers (NOMAD_OPEN_BROWSER).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPDIR="$ROOT/app"
PY="$APPDIR/python/bin/python3"

# The build is not notarized: a browser download marks every file as
# quarantined and macOS would refuse to run the bundled Python and its
# libraries one by one. The user allowed this launcher once (Privacy &
# Security > Open Anyway, or the xattr command in the download guide), so
# lift the mark from the rest of the folder — only ours, nothing else.
xattr -dr com.apple.quarantine "$ROOT" 2>/dev/null || true

if [ ! -x "$PY" ]; then
  echo "Nomad Studio: app/python/bin/python3 not found or not executable."
  echo "Extract the whole package and run NomadStudio.command from the NomadStudio folder."
  exit 1
fi

PORT="${PORT:-5123}"
export PORT

# Already running? Just open it.
if "$PY" -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:$PORT/api/health', timeout=3)" >/dev/null 2>&1; then
  open "http://localhost:$PORT" >/dev/null 2>&1 || echo "Nomad Studio is already running: http://localhost:$PORT"
  exit 0
fi

# Bundled libraries (app/lib) are registered by the python's nomad-lib.pth.
unset PYTHONPATH PYTHONHOME
export PYTHONNOUSERSITE=1
export PYTHONUTF8=1
export NOMAD_OPEN_BROWSER="${NOMAD_OPEN_BROWSER:-1}"

echo "Nomad Studio is starting on http://localhost:$PORT"
echo "The browser opens by itself when it is ready."
echo "Close this window (or press Ctrl+C) to stop Nomad Studio."
echo
exec "$PY" "$APPDIR/app.py"
