#!/usr/bin/env bash
# Nomad Studio - apply a prepared update on Linux and macOS (docs/APP_UPDATES.md
# 7.3-7.5). The bash twin of apply_update.ps1, same steps and same files.
#
# Started by the running app (app/services/update_service.py) from a copy in
# <root>/.nomad-update/, never from inside app/: the folder it renames must not
# hold the script. Detached in its own session, so it outlives the app.
#
#   1. wait for the app process to exit
#   2. app -> app.old, app.new -> app
#   3. copy the new launcher to the root and start it in the background
#   4. wait for /api/health to report the new version
#   5. if it never does: stop it, put app.old back, start the old version
# Every step goes to <root>/update.log; the outcome to <root>/update-result.json.
#
#   apply_update.sh <root> <wait-pid> <to> <from> <port> <launcher-name>
set -u

ROOT="$1"; WAIT_PID="$2"; TO="$3"; FROM="${4:-}"; PORT="${5:-5123}"; LAUNCHER_NAME="${6:-NomadStudio.sh}"
START_TIMEOUT=120
APP="$ROOT/app"; NEW="$ROOT/app.new"; OLD="$ROOT/app.old"
LAUNCHER="$ROOT/$LAUNCHER_NAME"
LOG="$ROOT/update.log"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >> "$LOG" 2>/dev/null || true; }

write_result() {  # ok(true|false) reason
  printf '{\n  "ok": %s,\n  "from": "%s",\n  "to": "%s",\n  "reason": "%s",\n  "at": "%s"\n}\n' \
    "$1" "$FROM" "$TO" "$2" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "$ROOT/update-result.json" 2>/dev/null \
    || log "could not write update-result.json"
}

# The app runs in the background after an update — no Terminal window, like
# the Windows console that starts hidden. Settings › "Close Nomad Studio"
# stops it; its output goes to <root>/nomad.log.
start_nomad() {
  log "starting $LAUNCHER_NAME in the background"
  NOMAD_OPEN_BROWSER=0 nohup /bin/bash "$LAUNCHER" >> "$ROOT/nomad.log" 2>&1 < /dev/null &
  LAUNCHER_PID=$!
}

app_running() {  # is a python from <folder> running?
  # Without pgrep (some minimal installs) we can't tell: say yes, so a slow
  # first start waits out the full timeout instead of being rolled back at 20 s.
  command -v pgrep >/dev/null 2>&1 || return 0
  pgrep -f "$1/python/bin/python3" >/dev/null 2>&1
}

stop_app() {
  [ -n "${LAUNCHER_PID:-}" ] && kill "$LAUNCHER_PID" 2>/dev/null
  pkill -f "$1/python/bin/python3" 2>/dev/null
  sleep 1
  pkill -9 -f "$1/python/bin/python3" 2>/dev/null
  return 0
}

health_version() {  # the version /api/health reports, or nothing
  "$APP/python/bin/python3" -c "
import json, urllib.request
try:
    print(json.load(urllib.request.urlopen('http://127.0.0.1:$PORT/api/health', timeout=3)).get('version', ''))
except Exception:
    pass" 2>/dev/null
}

log "---- update $FROM -> $TO (waiting for pid $WAIT_PID)"

# 1. The app exits about a second after asking for this.
for _ in $(seq 1 200); do
  kill -0 "$WAIT_PID" 2>/dev/null || break
  sleep 0.3
done
if kill -0 "$WAIT_PID" 2>/dev/null; then
  log "the app did not exit; nothing changed"
  write_result false app-did-not-exit
  exit 1
fi
sleep 0.5

if [ ! -f "$NEW/app.py" ]; then
  log "no prepared update in app.new"
  write_result false no-prepared-update
  start_nomad
  exit 1
fi

# 2. Swap folders. A running program's folder is not locked here, so no retries.
rm -rf "$OLD"
if ! mv "$APP" "$OLD"; then
  log "renaming app to app.old failed"
  write_result false folder-locked
  start_nomad
  exit 1
fi
if ! mv "$NEW" "$APP"; then
  log "renaming app.new to app failed; putting app.old back"
  mv "$OLD" "$APP"
  write_result false folder-locked
  start_nomad
  exit 1
fi
rm -f "$ROOT/update-pending.json"
log "folders swapped"

# 3. New launcher, then start.
if [ -f "$APP/launcher/$LAUNCHER_NAME" ]; then
  cp -f "$APP/launcher/$LAUNCHER_NAME" "$LAUNCHER" && chmod +x "$LAUNCHER"
fi
start_nomad

# 4. Health check.
ok=0
started=$(date +%s)
while [ $(( $(date +%s) - started )) -lt "$START_TIMEOUT" ]; do
  if [ "$(health_version)" = "$TO" ]; then ok=1; break; fi
  # Python gone for good (crashed on start): no point waiting the full timeout.
  if [ $(( $(date +%s) - started )) -gt 20 ] && ! app_running "$APP"; then
    log "the new version is not running"
    break
  fi
  sleep 1
done

if [ "$ok" = 1 ]; then
  log "update to $TO OK"
  write_result true ""
  exit 0
fi

# 5. Roll back.
log "the new version did not start; rolling back to $FROM"
stop_app "$APP"
FAILED="$ROOT/app.failed-$(printf '%s' "$TO" | tr -c '0-9A-Za-z.-' '_')"
rm -rf "$FAILED"
if mv "$APP" "$FAILED"; then
  mv "$OLD" "$APP"
fi
if [ -f "$APP/launcher/$LAUNCHER_NAME" ]; then
  cp -f "$APP/launcher/$LAUNCHER_NAME" "$LAUNCHER" && chmod +x "$LAUNCHER"
fi
write_result false did-not-start
start_nomad
exit 1
