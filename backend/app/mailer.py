from __future__ import annotations

import json
import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.config import (
    brevo_api_key,
    brevo_from_email,
    brevo_sender_name,
    email_backend,
    is_local_dev,
    otp_exp_minutes,
    smtp_from_email,
    smtp_host,
    smtp_pass,
    smtp_port,
    smtp_user,
)

logger = logging.getLogger(__name__)


class EmailSendError(RuntimeError):
    pass


def _is_delivery_configuration_error(err: EmailSendError) -> bool:
    """
    Returns True when the email send failed because the delivery provider
    isn't configured (missing credentials/host/dependencies), not because
    the recipient is invalid or the provider actively rejected the request.
    """
    msg = (str(err) or "").lower()
    needles = (
        "not configured",
        "provider not configured",
        "brevo_api_key",
        "brevo_from",
        "smtp_host",
        "smtp_from",
        "requests package not available",
    )
    return any(n in msg for n in needles)


def _send_via_brevo(*, to_email: str, subject: str, text: str) -> None:
    """
    Uses Brevo Transactional Email API:
    https://developers.brevo.com/docs/send-a-transactional-email
    """
    key = brevo_api_key()
    if not key:
        raise EmailSendError("BREVO_API_KEY not configured")
    sender_email = (brevo_from_email() or smtp_from_email()).strip()
    if not sender_email:
        raise EmailSendError("BREVO_FROM/SMTP_FROM not configured")

    # Local import: keep dependencies optional unless Brevo is used.
    try:
        import requests  # type: ignore
    except Exception as e:  # pragma: no cover
        raise EmailSendError(f"requests package not available: {e}") from e

    payload = {
        "sender": {"email": sender_email, "name": brevo_sender_name()},
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": text,
    }
    resp = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": key, "Content-Type": "application/json", "Accept": "application/json"},
        data=json.dumps(payload),
        timeout=15,
    )
    if not (200 <= int(resp.status_code) < 300):
        raise EmailSendError(f"Brevo send failed: HTTP {resp.status_code}: {resp.text[:500]}")


def _send_via_smtp(*, to_email: str, subject: str, text: str) -> None:
    host = smtp_host()
    port = int(smtp_port())
    user = smtp_user()
    password = smtp_pass()
    sender = smtp_from_email()
    if not host:
        raise EmailSendError("SMTP_HOST not configured")
    if not sender:
        raise EmailSendError("SMTP_FROM (or BREVO_FROM/SMTP_USER) not configured")

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text)

    timeout = 15
    if port == 465:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, timeout=timeout, context=context) as s:
            if user and password:
                s.login(user, password)
            s.send_message(msg)
        return

    with smtplib.SMTP(host, port, timeout=timeout) as s:
        s.ehlo()
        # Try STARTTLS if available (typical on 587).
        try:
            if s.has_extn("starttls"):
                s.starttls(context=ssl.create_default_context())
                s.ehlo()
        except Exception:
            # Some servers/proxies misreport; continue without TLS rather than crash.
            pass
        if user and password:
            s.login(user, password)
        s.send_message(msg)


def send_email(*, to_email: str, subject: str, text: str) -> None:
    """
    Prefer Brevo if configured; otherwise fall back to SMTP.
    """
    to_email = (to_email or "").strip()
    if not to_email or "@" not in to_email:
        raise EmailSendError("Invalid recipient email")

    backend = email_backend()
    if backend in ("console", "log"):
        logger.warning(
            "EMAIL_BACKEND=console: to=%s subject=%s\n%s",
            to_email,
            subject,
            text,
        )
        return

    if backend == "brevo":
        _send_via_brevo(to_email=to_email, subject=subject, text=text)
        return

    if backend == "smtp":
        _send_via_smtp(to_email=to_email, subject=subject, text=text)
        return

    # "auto" (default): prefer Brevo when API key is present.
    if brevo_api_key():
        _send_via_brevo(to_email=to_email, subject=subject, text=text)
        return

    # If SMTP is configured, try it; otherwise we may fall back in local dev.
    if smtp_host():
        _send_via_smtp(to_email=to_email, subject=subject, text=text)
        return

    # Dev-friendly fallback (no external email service configured).
    if is_local_dev():
        logger.warning(
            "No email provider configured; falling back to console output in local dev. "
            "Set EMAIL_BACKEND=smtp/brevo (or configure SMTP_/BREVO_ env vars) for real delivery.\n"
            "to=%s subject=%s\n%s",
            to_email,
            subject,
            text,
        )
        return

    raise EmailSendError(
        "Email provider not configured. Set BREVO_API_KEY+BREVO_FROM (Brevo) or SMTP_HOST+SMTP_FROM (SMTP)."
    )


def send_otp_email(*, to_email: str, otp: str, purpose: str) -> str:
    mins = otp_exp_minutes()
    purpose_label = "Login" if (purpose or "").strip().lower() == "login" else "Password reset"
    subject = f"{purpose_label} OTP"
    text = (
        f"Your {purpose_label} OTP is: {otp}\n\n"
        f"This code expires in {mins} minutes.\n\n"
        "If you did not request this, you can ignore this email."
    )
    try:
        send_email(to_email=to_email, subject=subject, text=text)
        return "email"
    except EmailSendError as e:
        # If email isn't configured, still allow OTP flows to work by logging
        # the OTP to server logs (useful for initial deployments / staging).
        if _is_delivery_configuration_error(e):
            logger.warning(
                "OTP delivery fallback (email not configured): purpose=%s to=%s otp=%s expires_in_minutes=%s error=%s",
                purpose,
                to_email,
                otp,
                mins,
                str(e),
            )
            return "console"
        raise
