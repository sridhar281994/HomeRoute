"""
ASGI entrypoint for deployments (e.g. Render).

This repository's FastAPI app lives in `backend/app/main.py` and uses imports like
`from app.db ...`, which requires `backend/` to be on `PYTHONPATH`.

By providing a repo-root `main.py`, Render can run:
  uvicorn main:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import sys
from pathlib import Path


_ROOT = Path(__file__).resolve().parent
_BACKEND_DIR = _ROOT / "backend"

# Ensure `import app...` resolves to `backend/app/...`
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.main import app  # noqa: E402

