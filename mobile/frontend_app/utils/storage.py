from __future__ import annotations

import json
import os
from typing import Any


def _store_path() -> str:
    # Keep it simple + portable: store next to project root when running locally.
    # On mobile, you can swap this to App.get_running_app().user_data_dir later.
    return os.environ.get("APP_SESSION_PATH", os.path.join(os.getcwd(), ".session.json"))


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
    d["user"] = user or {}
    d["remember_me"] = bool(remember)
    _write(d)


def clear_session() -> None:
    d = _read()
    d.pop("token", None)
    d.pop("user", None)
    _write(d)


def get_session() -> dict[str, Any]:
    d = _read()
    return {"token": d.get("token") or "", "user": d.get("user") or {}}


def get_token() -> str:
    return str(get_session().get("token") or "")


def get_user() -> dict[str, Any]:
    return dict(get_session().get("user") or {})

