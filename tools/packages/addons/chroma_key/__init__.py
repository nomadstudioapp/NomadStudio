"""NomadStudio Addon: Chroma Key.

Removes a solid or vignetted background by keying on chrominance (Cb/Cr in
YCbCr) rather than raw RGB distance, so gradients/vignettes in an otherwise
flat background don't fool the key. 100% local numpy/scipy processing — no
ComfyUI/AI model required. Structure mirrors the pixel_matcher reference
addon (see addons/README.md).
"""

from __future__ import annotations

from flask import Flask

ADDON_INFO = {
    "name": "Chroma Key",
    "version": (1, 0, 0),
    "description": "Remove a solid or vignetted background by color (chrominance-based keying), with despeckle, feathering and edge decontamination.",
    "author": "NomadStudio",
    "url_prefix": "/api",
}


def register(app: Flask) -> None:
    """Register this addon's blueprint with the Flask app."""
    from .routes import chroma_key_bp
    app.register_blueprint(chroma_key_bp, url_prefix=ADDON_INFO["url_prefix"])


def unregister() -> None:
    """Unregister hook (no-op for now — Flask does not support hot-unload)."""
    pass
