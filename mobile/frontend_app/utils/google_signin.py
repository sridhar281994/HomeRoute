from __future__ import annotations

from typing import Any, Callable

from kivy.clock import Clock
from kivy.utils import platform

# ------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------
REQUEST_CODE_GOOGLE_SIGN_IN = 4915

_bound = False
_pending: dict[str, Any] = {}

_LOG_TAG = "Quickrent4uGoogleSignIn"
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

    cid = (server_client_id or "").strip()
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

                # Try modern API first
                try:
                    GoogleSignIn = autoclass(
                        "com.google.android.gms.auth.api.signin.GoogleSignIn"
                    )
                    task = GoogleSignIn.getSignedInAccountFromIntent(data)
                    account = task.getResult()
                except Exception:
                    # Fallback legacy API
                    Auth = autoclass("com.google.android.gms.auth.api.Auth")
                    result = Auth.GoogleSignInApi.getSignInResultFromIntent(data)
                    if (
                        result is None
                        or hasattr(result, "isSuccess")
                        and not bool(result.isSuccess())
                    ):
                        fail("Google Sign-In failed.")
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

            # 🚫 NO getClient(), NO listeners
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
