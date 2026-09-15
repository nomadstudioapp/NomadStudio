"""Compatibility shim — pixel_matcher logic has moved to addons/pixel_matcher/service.py.

Importing this module still works so existing code referencing
``app.services.pixel_matcher_service`` does not break during the transition.
"""

from __future__ import annotations

# Re-export everything from the canonical addon location.
from addons.pixel_matcher.service import (  # noqa: F401
    detect_optimal_pixel_size,
    pixel_matcher,
    process_image_bytes,
)