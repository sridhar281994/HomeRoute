from __future__ import annotations

import json
import os
from typing import Any


def _store_path() -> str:
    """
    Return a writable path for small app state (session/config).

    - Desktop/dev: allow overriding via APP_SESSION_PATH, else use CWD.
    - Android/iOS: use Kivy's user_data_dir (writable sandbox).
    """
    override = (os.environ.get("APP_SESSION_PATH") or "").strip()
    if override:
        return override
    try:
        from kivy.app import App

        app = App.get_running_app()
        if app and getattr(app, "user_data_dir", None):
            return os.path.join(str(app.user_data_dir), ".session.json")
    except Exception:
        pass
    return os.path.join(os.getcwd(), ".session.json")


def _read() -> dict[str, Any]:
    path = _store_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _write(data: dict[str, Any]) -> None:
    path = _store_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        # Best-effort; UI should still function.
        pass


def set_remember_me(value: bool) -> None:
    d = _read()
    d["remember_me"] = bool(value)
    _write(d)


def get_remember_me() -> bool:
    return bool(_read().get("remember_me", False))


def set_session(*, token: str, user: dict[str, Any], remember: bool) -> None:
    d = _read()
    d["token"] = token or ""
    # Normalize any relative upload URLs to absolute URLs for Kivy AsyncImage.
    try:
        from frontend_app.utils.api import _base_url  # local import to avoid import cycles

        base = str(_base_url() or "").rstrip("/")
        u = dict(user or {})
        for key in ["profile_image_url"]:
            v = str(u.get(key) or "").strip()
            if v.startswith("/"):
                u[key] = f"{base}{v}"
        d["user"] = u
    except Exception:
        d["user"] = user or {}
    d["remember_me"] = bool(remember)
    d["guest"] = False
    _write(d)


def clear_session() -> None:
    d = _read()
    d.pop("token", None)
    d.pop("user", None)
    d.pop("guest", None)
    _write(d)


def set_guest_session() -> None:
    """
    Start a local guest session (no auth token).
    The UI uses this flag to gate restricted actions and show guest mode.
    """
    d = _read()
    d["token"] = ""
    d["user"] = {"name": "Guest", "role": "guest"}
    d["remember_me"] = False
    d["guest"] = True
    _write(d)


def get_session() -> dict[str, Any]:
    d = _read()
    return {
        "token": d.get("token") or "",
        "user": d.get("user") or {},
        "remember_me": bool(d.get("remember_me", False)),
        "guest": bool(d.get("guest", False)),
    }


def get_token() -> str:
    return str(get_session().get("token") or "")


def get_user() -> dict[str, Any]:
    return dict(get_session().get("user") or {})


# -----------------------
# App config (API base URL, etc.)
# -----------------------
def get_api_base_url() -> str:
    """
    Mobile needs an explicit API base URL (e.g. https://api.example.com).
    Stored locally so OTP/login works on real devices.
    """
    return str(_read().get("api_base_url") or "").strip().rstrip("/")


def set_api_base_url(url: str) -> None:
    u = str(url or "").strip().rstrip("/")
    d = _read()
    d["api_base_url"] = u
    _write(d)

