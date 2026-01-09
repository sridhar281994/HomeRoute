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


def otp_exp_minutes() -> int:
    """
    OTP expiry duration in minutes.
    Set via env `OTP_EXP_MINUTES` (Render).
    """
    raw = (os.environ.get("OTP_EXP_MINUTES") or "").strip()
    try:
        v = int(raw or "10")
    except Exception:
        v = 10
    # Reasonable bounds to avoid foot-guns.
    if v < 1:
        v = 1
    if v > 60:
        v = 60
    return v


def brevo_api_key() -> str:
    return (os.environ.get("BREVO_API_KEY") or "").strip()


def brevo_from_email() -> str:
    return (os.environ.get("BREVO_FROM") or "").strip()


def smtp_host() -> str:
    return (os.environ.get("SMTP_HOST") or "").strip()


def smtp_port() -> int:
    raw = (os.environ.get("SMTP_PORT") or "").strip()
    try:
        return int(raw or "587")
    except Exception:
        return 587


def smtp_user() -> str:
    return (os.environ.get("SMTP_USER") or "").strip()


def smtp_pass() -> str:
    return (os.environ.get("SMTP_PASS") or "").strip()


def smtp_from_email() -> str:
    # Allow either SMTP_FROM or BREVO_FROM as the sender address.
    return ((os.environ.get("SMTP_FROM") or "").strip() or brevo_from_email() or smtp_user()).strip()

