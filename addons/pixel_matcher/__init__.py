"""NomadStudio Addon: Pixel Matcher.

Converts images to pixel art using KMeans colour quantisation.
This is the reference addon — its structure serves as the template for all
other NomadStudio addons (see addons/README.md).
"""

from __future__ import annotations

from flask import Flask

# ---------------------------------------------------------------------------
# Addon metadata — equivalent to Blender's bl_info dict.
# Required fields: name, version, description, author.
# ---------------------------------------------------------------------------
ADDON_INFO = {
    "name": "Pixel Matcher",
    "version": (1, 0, 0),
    "description": "Convert images to pixel art via KMeans colour quantisation.",
    "author": "NomadStudio",
    "url_prefix": "/api",          # Flask blueprint url_prefix
}


def register(app: Flask) -> None:
    """Register this addon's blueprint with the Flask app."""
    from .routes import pixel_matcher_bp
    app.register_blueprint(pixel_matcher_bp, url_prefix=ADDON_INFO["url_prefix"])


def unregister() -> None:
    """Unregister hook (no-op for now — Flask does not support hot-unload)."""
    pass
