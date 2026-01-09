from __future__ import annotations

import os


def database_url() -> str:
    # Your GitHub secret should provide this in production/CI.
    # Fallback for local dev:
    url = os.environ.get("DATABASE_URL") or "sqlite:///./local.db"
    # Some managed providers still supply `postgres://...` which SQLAlchemy treats as invalid.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def jwt_secret() -> str:
    return os.environ.get("JWT_SECRET") or "dev-secret-change-me"

