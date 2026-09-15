"""Route modules for models API grouped by domain."""

from . import mobile_routes  # noqa: F401  registers /api/mobile/* endpoints
from . import prompt_routes   # noqa: F401  registers /models/chat/edit-prompt, convert-to-json, regenerate, blend
from . import vision_routes   # noqa: F401  registers /models/chat/describe-image, edit-description, generate-style
from . import studio_routes   # noqa: F401  registers /models/chat/studio-* and studio-ideogram-*
from . import styles_routes     # noqa: F401  registers /styles/* endpoints
from . import generation_routes # noqa: F401  registers /models/imports/*/generate, submit, queue
