from __future__ import annotations

import json
import os
from typing import Any, Callable

from kivy.clock import Clock
from kivy.resources import resource_find
from kivy.utils import platform

# ------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------
REQUEST_CODE_GOOGLE_SIGN_IN = 4915

_bound = False
_pending: dict[str, Any] = {}

_LOG_TAG = "FlatnowGoogleSignIn"
_log_fn: Callable[[str], None] | None = None


def _log(message: str) -> None:
    """Log to Android logcat when available; fallback to print."""
    global _log_fn
    if _log_fn is None:
        try:
            if platform == "android":
                from jnius import autoclass  # type: ignore

                Log = autoclass("android.util.Log")

                def _android_log(msg: str) -> None:
                    Log.d(_LOG_TAG, str(msg))

                _log_fn = _android_log
            else:
                _log_fn = lambda msg: print(f"[{_LOG_TAG}] {msg}")
        except Exception:
            _log_fn = lambda msg: print(f"[{_LOG_TAG}] {msg}")
    try:
        _log_fn(str(message))
    except Exception:
        pass


# ------------------------------------------------------------
# CLIENT ID RESOLUTION (google-services.json integration)
# ------------------------------------------------------------
def _extract_web_client_id_from_google_services(path: str) -> str:
    """
    Extract the "web" OAuth client id (client_type == 3) from google-services.json.
    This is the value expected by requestIdToken(<web-client-id>).
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return ""

    try:
        clients = data.get("client") or []
        if not isinstance(clients, list):
            return ""
        for c in clients:
            oauth = (c or {}).get("oauth_client") or []
            if not isinstance(oauth, list):
                continue
            for entry in oauth:
                if (entry or {}).get("client_type") == 3 and (entry or {}).get("client_id"):
                    return str(entry.get("client_id") or "").strip()
            # Some files nest the web client id here instead.
            services = (c or {}).get("services") or {}
            inv = (services or {}).get("appinvite_service") or {}
            other = (inv or {}).get("other_platform_oauth_client") or []
            if isinstance(other, list):
                for entry in other:
                    if (entry or {}).get("client_type") == 3 and (entry or {}).get("client_id"):
                        return str(entry.get("client_id") or "").strip()
    except Exception:
        return ""
    return ""


def _resolve_server_client_id(server_client_id: str) -> str:
    """
    Prefer explicitly provided client id, then attempt to read from packaged
    google-services.json (Android-safe default), then environment variables.
    """
    cid = (server_client_id or "").strip()
    if cid:
        return cid

    # In this project the file is checked in as mobile/google-services.json and is included
    # in the packaged app sources. resource_find() works on both desktop and Android.
    path = resource_find("google-services.json") or ""
    if path and os.path.exists(path):
        extracted = _extract_web_client_id_from_google_services(path)
        if extracted:
            _log("Resolved Google web client id from google-services.json.")
            return extracted

    env_cid = (os.environ.get("GOOGLE_OAUTH_CLIENT_ID") or os.environ.get("GOOGLE_WEB_CLIENT_ID") or "").strip()
    if env_cid:
        return env_cid

    # Fallback: try the repo-relative path for local/dev runs.
    # Expected layout: mobile/google-services.json (this file is in mobile/frontend_app/utils/)
    repo_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "google-services.json")
    )
    if os.path.exists(repo_path):
        extracted = _extract_web_client_id_from_google_services(repo_path)
        if extracted:
            _log("Resolved Google web client id from repo google-services.json.")
            return extracted

    return ""


# ------------------------------------------------------------
# LEGACY SIGN-IN STARTER (NO LISTENERS — ANDROID SAFE)
# ------------------------------------------------------------
def _legacy_start_sign_in(
    *,
    act,
    gso,
    request_code: int,
    autoclass,
    on_error: Callable[[str], None],
) -> None:
    Auth = autoclass("com.google.android.gms.auth.api.Auth")
    GoogleApiClientBuilder = autoclass(
        "com.google.android.gms.common.api.GoogleApiClient$Builder"
    )

    # Build client WITHOUT listener (avoids classloader crash)
    client = (
        GoogleApiClientBuilder(act)
        .addApi(Auth.GOOGLE_SIGN_IN_API, gso)
        .build()
    )

    try:
        client.connect()
    except Exception:
        pass

    # Keep reference alive
    _pending["legacy_client"] = client

    _log("Launching legacy Google Sign-In intent.")
    intent = Auth.GoogleSignInApi.getSignInIntent(client)
    act.startActivityForResult(intent, request_code)


# ------------------------------------------------------------
# MODERN SIGN-IN STARTER (PREFERRED)
# ------------------------------------------------------------
def _modern_start_sign_in(
    *,
    act,
    gso,
    request_code: int,
    autoclass,
) -> None:
    GoogleSignIn = autoclass("com.google.android.gms.auth.api.signin.GoogleSignIn")
    client = GoogleSignIn.getClient(act, gso)
    _pending["modern_client"] = client  # keep alive
    _log("Launching modern Google Sign-In intent.")
    intent = client.getSignInIntent()
    act.startActivityForResult(intent, request_code)


# ------------------------------------------------------------
# PUBLIC ENTRY POINT
# ------------------------------------------------------------
def google_sign_in(
    *,
    server_client_id: str,
    on_success: Callable[[str, dict[str, str]], None],
    on_error: Callable[[str], None],
) -> None:
    _log("Starting Google Sign-In flow.")

    if platform != "android":
        Clock.schedule_once(
            lambda *_: on_error("Google Sign-In is only available on Android builds."),
            0,
        )
        return

    cid = _resolve_server_client_id(server_client_id)
    if not cid:
        Clock.schedule_once(
            lambda *_: on_error(
                "Google Sign-In is not configured (missing GOOGLE_OAUTH_CLIENT_ID)."
            ),
            0,
        )
        return

    try:
        from android import activity  # type: ignore
        from android.runnable import run_on_ui_thread  # type: ignore
        from jnius import autoclass  # type: ignore
    except Exception as e:
        msg = f"Google Sign-In is unavailable in this build: {e}"
        _log(msg)
        Clock.schedule_once(lambda *_dt, msg=msg: on_error(msg), 0)
        return

    global _bound
    _pending.clear()
    _pending["on_success"] = on_success
    _pending["on_error"] = on_error

    # ---------------------------------------------------------
    # Activity result binding (only once, ANDROID ONLY)
    # ---------------------------------------------------------
    if not _bound:
        _bound = True
        _log("Binding activity result listener.")

        def _on_activity_result(request_code: int, result_code: int, data) -> bool:
            if request_code != REQUEST_CODE_GOOGLE_SIGN_IN:
                return False

            def fail(msg: str) -> None:
                _log(f"Sign-in failed: {msg}")
                cb = _pending.get("on_error")
                if cb:
                    Clock.schedule_once(lambda *_: cb(str(msg)), 0)

            try:
                # NOTE:
                # Legacy Google Sign-In may return RESULT_CANCELED even on success.
                # Do NOT rely on result_code. Always parse the intent.

                if data is None:
                    fail("Google Sign-In returned no data.")
                    return True

                _log("Parsing Google Sign-In intent.")

                # Try modern API first (Task-based)
                try:
                    GoogleSignIn = autoclass(
                        "com.google.android.gms.auth.api.signin.GoogleSignIn"
                    )
                    task = GoogleSignIn.getSignedInAccountFromIntent(data)
                    ApiException = autoclass("com.google.android.gms.common.api.ApiException")

                    # Prefer the typed getResult(ApiException.class) to surface status codes
                    # like DEVELOPER_ERROR (10) reliably across Play Services versions.
                    account = task.getResult(ApiException)
                except Exception as exc:
                    # If this is an ApiException, surface the status code string.
                    try:
                        code = int(exc.getStatusCode()) if hasattr(exc, "getStatusCode") else None
                    except Exception:
                        code = None
                    if code is not None:
                        status_str = ""
                        try:
                            GoogleSignInStatusCodes = autoclass(
                                "com.google.android.gms.auth.api.signin.GoogleSignInStatusCodes"
                            )
                            status_str = str(GoogleSignInStatusCodes.getStatusCodeString(code) or "")
                        except Exception:
                            status_str = ""
                        msg = f"Google Sign-In failed (status={code}{': ' + status_str if status_str else ''})."
                        # Make the most common misconfig extra explicit.
                        if code == 10:
                            msg += " (DEVELOPER_ERROR: check package name + SHA-1 / app signing in Google/Firebase config)"
                        fail(msg)
                        return True
                    # Fallback legacy API
                    Auth = autoclass("com.google.android.gms.auth.api.Auth")
                    result = Auth.GoogleSignInApi.getSignInResultFromIntent(data)
                    if (
                        result is None
                        or hasattr(result, "isSuccess")
                        and not bool(result.isSuccess())
                    ):
                        # Try to pull a Status code (e.g. DEVELOPER_ERROR=10) for better debugging.
                        msg = "Google Sign-In failed."
                        try:
                            status = result.getStatus() if result is not None and hasattr(result, "getStatus") else None
                            code = int(status.getStatusCode()) if status is not None and hasattr(status, "getStatusCode") else None
                            if code is not None:
                                status_str = ""
                                try:
                                    CommonStatusCodes = autoclass("com.google.android.gms.common.api.CommonStatusCodes")
                                    status_str = str(CommonStatusCodes.getStatusCodeString(code) or "")
                                except Exception:
                                    status_str = ""
                                msg = f"Google Sign-In failed (status={code}{': ' + status_str if status_str else ''})."
                        except Exception:
                            pass
                        fail(msg)
                        return True
                    account = result.getSignInAccount()

                token = str(account.getIdToken() or "").strip()
                if not token:
                    fail("Google Sign-In did not return an ID token.")
                    return True

                profile = {
                    "email": str(account.getEmail() or "").strip(),
                    "name": str(account.getDisplayName() or "").strip(),
                }

                cb = _pending.get("on_success")
                if cb:
                    Clock.schedule_once(lambda *_: cb(token, profile), 0)

            except Exception as e:
                fail(str(e) or "Google Sign-In failed.")

            return True

        activity.bind(on_activity_result=_on_activity_result)

    # ---------------------------------------------------------
    # Start sign-in on UI thread (LEGACY ONLY)
    # ---------------------------------------------------------
    @run_on_ui_thread
    def _start() -> None:
        try:
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            act = PythonActivity.mActivity

            GoogleSignInOptions = autoclass(
                "com.google.android.gms.auth.api.signin.GoogleSignInOptions"
            )
            GoogleSignInOptionsBuilder = autoclass(
                "com.google.android.gms.auth.api.signin.GoogleSignInOptions$Builder"
            )

            builder = GoogleSignInOptionsBuilder(GoogleSignInOptions.DEFAULT_SIGN_IN)
            gso = builder.requestEmail().requestIdToken(cid).build()

            # Prefer modern flow; fallback to legacy if needed.
            try:
                _modern_start_sign_in(
                    act=act,
                    gso=gso,
                    request_code=REQUEST_CODE_GOOGLE_SIGN_IN,
                    autoclass=autoclass,
                )
            except Exception as e:
                _log(f"Modern sign-in unavailable, falling back: {e}")
                _legacy_start_sign_in(
                    act=act,
                    gso=gso,
                    request_code=REQUEST_CODE_GOOGLE_SIGN_IN,
                    autoclass=autoclass,
                    on_error=lambda msg: Clock.schedule_once(
                        lambda *_dt, msg=msg: on_error(msg), 0
                    ),
                )

        except Exception as e:
            cb = _pending.get("on_error")
            if cb:
                msg = str(e) or "Failed to start Google Sign-In."
                _log(msg)
                Clock.schedule_once(lambda *_dt, msg=msg: cb(msg), 0)

    _start()
