from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def sms_backend() -> str:
    """
    SMS delivery backend.
    - "console" (default): log the SMS payload (safe fallback)
    - "disabled": do nothing
    """
    return (os.environ.get("SMS_BACKEND") or "console").strip().lower()


def send_sms(*, to_phone: str, text: str) -> str:
    """
    Sends an SMS message (best-effort).

    This project doesn't ship with a paid SMS provider integration by default.
    In production, wire this to Twilio/MSG91/etc and keep the same interface.
    """
    to_phone = (to_phone or "").strip()
    text = (text or "").strip()
    if not to_phone or not text:
        return "skipped"

    backend = sms_backend()
    if backend in {"disabled", "off", "none"}:
        return "disabled"

    # Default safe fallback.
    logger.warning("SMS_BACKEND=%s: to=%s\n%s", backend, to_phone, text)
    return "console"

