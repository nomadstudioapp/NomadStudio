import os
from pathlib import Path

from app import create_app

app = create_app()

# Portable builds ship a portable.json next to this file (docs/APP_UPDATES.md §2).
IS_PORTABLE = (Path(__file__).resolve().parent / "portable.json").is_file()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5123"))
    # The Werkzeug debugger must never be reachable from the network in a
    # portable build: debug (and its auto-reloader) is for source checkouts
    # only. NOMAD_DEBUG=0/1 overrides either way.
    debug = os.getenv("NOMAD_DEBUG", "0" if IS_PORTABLE else "1") == "1"
    app.run(debug=debug, host="0.0.0.0", port=port, threaded=True)
