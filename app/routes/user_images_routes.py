"""Images the user creates, served from the data folder (app/paths.py).

Build characters and backgrounds and template pack images used to be written
into ``app/static/images/…`` and are still referenced by those URLs (in the
JS and inside stored data), so the same URLs are kept: these rules are more
specific than Flask's ``/static/<path>`` and win over it. A file the app ships
in static/ with the same name is used when the data folder has none.
"""

from __future__ import annotations

import os

from flask import Blueprint, abort, send_from_directory
from werkzeug.security import safe_join

from .. import paths

user_images_bp = Blueprint("user_images", __name__)

_KINDS = ("characters", "backgrounds", "template_packs")


def _serve(kind: str, filename: str):
    for base in (paths.user_images(kind), paths.APP_DIR / "static" / "images" / kind):
        full = safe_join(str(base), filename)
        if full and os.path.isfile(full):
            response = send_from_directory(base, filename)
            response.headers["Cache-Control"] = "no-cache"
            return response
    abort(404)


for _kind in _KINDS:
    user_images_bp.add_url_rule(
        f"/static/images/{_kind}/<path:filename>",
        endpoint=f"serve_{_kind}",
        view_func=lambda filename, kind=_kind: _serve(kind, filename),
    )
