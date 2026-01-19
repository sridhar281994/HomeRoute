"""
Compatibility package for desktop/dev environments.

The Android build uses `mobile/` as the project root (Buildozer `source.dir = .`),
so `frontend_app` is a top-level package at runtime.

When running from the repository root (or opening the repo in IDEs like PyCharm),
`frontend_app` actually lives under `mobile/frontend_app`. This shim ensures
imports like `from frontend_app.utils.api import ...` resolve in both contexts.
"""

from __future__ import annotations

import os
import sys
from pkgutil import extend_path


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_MOBILE_DIR = os.path.join(_REPO_ROOT, "mobile")

# Make sure `mobile/frontend_app/...` is importable as `frontend_app/...`.
if os.path.isdir(_MOBILE_DIR) and _MOBILE_DIR not in sys.path:
    sys.path.insert(0, _MOBILE_DIR)

# Allow `frontend_app` to be spread across multiple locations.
__path__ = extend_path(__path__, __name__)  # type: ignore[name-defined]

