from __future__ import annotations

from typing import Callable

from kivy.clock import Clock
from kivy.utils import platform


def _android_sdk_int() -> int:
    if platform != "android":
        return 0
    try:
        from jnius import autoclass  # type: ignore

        BuildVERSION = autoclass("android.os.Build$VERSION")
        return int(BuildVERSION.SDK_INT)
    except Exception:
        return 0


def _get_android_perm_api():
    """
    Returns (Permission, check_permission, request_permissions) or (None, None, None).
    """
    if platform != "android":
        return None, None, None
    try:
        from android.permissions import Permission, check_permission, request_permissions  # type: ignore

        return Permission, check_permission, request_permissions
    except Exception:
        return None, None, None


def required_media_permissions() -> list[str]:
    """
    Permissions needed for picking/uploading images/videos.
    """
    sdk = _android_sdk_int()
    if sdk >= 33:
        # Android 13+: granular media permissions.
        return ["android.permission.READ_MEDIA_IMAGES", "android.permission.READ_MEDIA_VIDEO"]
    # Android <= 12L
    return ["android.permission.READ_EXTERNAL_STORAGE"]


def required_location_permissions() -> list[str]:
    return ["android.permission.ACCESS_COARSE_LOCATION", "android.permission.ACCESS_FINE_LOCATION"]


def ensure_permissions(perms: list[str], *, on_result: Callable[[bool], None]) -> None:
    """
    Ensure Android runtime permissions are granted.
    Calls on_result(True/False) on the Kivy main thread.
    """
    if platform != "android":
        Clock.schedule_once(lambda *_: on_result(True), 0)
        return

    Permission, check_permission, request_permissions = _get_android_perm_api()
    if not check_permission or not request_permissions:
        # Older/unsupported runtime-perms environment: proceed best-effort.
        Clock.schedule_once(lambda *_: on_result(True), 0)
        return

    req = [str(p) for p in (perms or []) if str(p)]
    if not req:
        Clock.schedule_once(lambda *_: on_result(True), 0)
        return

    try:
        already = all(bool(check_permission(p)) for p in req)
    except Exception:
        already = False

    if already:
        Clock.schedule_once(lambda *_: on_result(True), 0)
        return

    def _cb(_permissions, grants) -> None:
        try:
            ok = bool(grants) and all(bool(x) for x in grants)
        except Exception:
            ok = False
        Clock.schedule_once(lambda *_: on_result(ok), 0)

    try:
        request_permissions(req, _cb)
    except Exception:
        Clock.schedule_once(lambda *_: on_result(False), 0)

