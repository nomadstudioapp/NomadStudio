import os
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from app import create_app

app = create_app()

# Portable builds ship a portable.json next to this file (docs/APP_UPDATES.md §2).
IS_PORTABLE = (Path(__file__).resolve().parent / "portable.json").is_file()


def _open_browser_when_ready(port: int) -> None:
    """Open the default browser once the server answers — same idea as
    ComfyUI's --auto-launch. Polls 127.0.0.1 (not "localhost", which can
    resolve to IPv6 ::1 first on Windows while the server listens on IPv4)."""
    for _ in range(120):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2):
                webbrowser.open(f"http://localhost:{port}")
                return
        except Exception:  # noqa: BLE001 — not up yet
            time.sleep(0.5)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5123"))
    # The Werkzeug debugger must never be reachable from the network in a
    # portable build: debug (and its auto-reloader) is for source checkouts
    # only. NOMAD_DEBUG=0/1 overrides either way.
    debug = os.getenv("NOMAD_DEBUG", "0" if IS_PORTABLE else "1") == "1"
    # The launcher sets NOMAD_OPEN_BROWSER=1. Skipped in the reloader's child
    # process so a debug run doesn't open two tabs.
    if os.getenv("NOMAD_OPEN_BROWSER") == "1" and os.getenv("WERKZEUG_RUN_MAIN") != "true":
        threading.Thread(target=_open_browser_when_ready, args=(port,), daemon=True).start()
    app.run(debug=debug, host="0.0.0.0", port=port, threaded=True)
