from __future__ import annotations

import os


def database_url() -> str:
    # Your GitHub secret should provide this in production/CI.
    # Fallback for local dev:
    return os.environ.get("DATABASE_URL") or "sqlite:///./local.db"


def jwt_secret() -> str:
    return os.environ.get("JWT_SECRET") or "dev-secret-change-me"

