from __future__ import annotations

from typing import Any, Callable

from kivy.clock import Clock
from kivy.utils import platform

REQUEST_CODE_GOOGLE_SIGN_IN = 4915

GOOGLE_OAUTH_CLIENT_ID = "634110997767-juj3od861h6po1udb0huea59hog0931l.apps.googleusercontent.com"

_bound = False
_pending: dict[str, Any] = {}


def _legacy_start_sign_in(*, act, gso, request_code: int, autoclass, on_error: Callable[[str], None]) -> None:
    """
    Legacy Google Sign-In flow using GoogleApiClient.
    This avoids GoogleSignIn.getClient() which breaks under PyJNIus.
    """
    try:
        from jnius import PythonJavaClass, java_method  # type: ignore
    except Exception as e:
        raise RuntimeError(f"Legacy Google Sign-In unavailable: {e}") from e

    # Keep references alive to avoid GC while the flow is in progress.
    class _OnConnectionFailedListener(PythonJavaClass):  # type: ignore[misc]
        __javainterfaces__ = [
            "com/google/android/gms/common/api/GoogleApiClient$OnConnectionFailedListener"
        ]

        def __init__(self, cb: Callable[[str], None]):
            super().__init__()
            self._cb = cb

        @java_method("(Lcom/google/android/gms/common/ConnectionResult;)V")
        def onConnectionFailed(self, connection_result) -> None:
            try:
                msg = str(connection_result) if connection_result is not None else "Connection failed."
            except Exception:
                msg = "Connection failed."
            self._cb(msg)

    Auth = autoclass("com.google.android.gms.auth.api.Auth")
    GoogleApiClientBuilder = autoclass(
        "com.google.android.gms.common.api.GoogleApiClient$Builder"
    )

    listener = _OnConnectionFailedListener(on_error)
    client = (
        GoogleApiClientBuilder(act)
        .addApi(Auth.GOOGLE_SIGN_IN_API, gso)
        .addOnConnectionFailedListener(listener)
        .build()
    )

    try:
        client.connect()
    except Exception:
        pass

    # Keep references alive
    _pending["legacy_client"] = client
    _pending["legacy_listener"] = listener

    intent = Auth.GoogleSignInApi.getSignInIntent(client)
    act.startActivityForResult(intent, request_code)


def google_sign_in(
    *,
    server_client_id: str,
    on_success: Callable[[str, dict[str, str]], None],
    on_error: Callable[[str], None],
) -> None:
    """
    Start Google Sign-In on Android and return an ID token.
    Uses legacy intent flow for maximum stability.
    """
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

    # Android imports
    try:
        from android import activity  # type: ignore
        from android.runnable import run_on_ui_thread  # type: ignore
        from jnius import autoclass  # type: ignore
    except Exception as e:
        msg = f"Google Sign-In is unavailable in this build: {e}"
        Clock.schedule_once(lambda *_dt, msg=msg: on_error(msg), 0)
        return

    global _bound
    _pending.clear()
    _pending["on_success"] = on_success
    _pending["on_error"] = on_error

    # ---------------------------------------------------------
    # Activity result binding (only once)
    # ---------------------------------------------------------
    if not _bound:
        _bound = True

        def _on_activity_result(request_code: int, result_code: int, data) -> bool:
            if request_code != REQUEST_CODE_GOOGLE_SIGN_IN:
                return False

            def fail(msg: str) -> None:
                cb = _pending.get("on_error")
                if cb:
                    cb(str(msg))

            try:
                GoogleSignIn = autoclass(
                    "com.google.android.gms.auth.api.signin.GoogleSignIn"
                )
                ApiException = autoclass(
                    "com.google.android.gms.common.api.ApiException"
                )

                # -----------------------------
                # Try modern API first (safe)
                # -----------------------------
                try:
                    if hasattr(GoogleSignIn, "getSignedInAccountFromIntent"):
                        task = GoogleSignIn.getSignedInAccountFromIntent(data)
                        account = task.getResult(ApiException)
                    else:
                        raise RuntimeError("Modern API unavailable")
                except Exception:
                    # -----------------------------
                    # Legacy API fallback
                    # -----------------------------
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
                    cb(token, profile)

            except Exception as e:
                fail(str(e) or "Google Sign-In failed.")

            return True

        activity.bind(on_activity_result=_on_activity_result)

    # ---------------------------------------------------------
    # Start sign-in on UI thread (legacy only)
    # ---------------------------------------------------------
    @run_on_ui_thread
    def _start() -> None:
        try:
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            act = PythonActivity.mActivity

            GoogleSignInOptions = autoclass(
                "com.google.android.gms.auth.api.signin.GoogleSignInOptions"
            )

            builder = GoogleSignInOptions.Builder(
                GoogleSignInOptions.DEFAULT_SIGN_IN
            )
            gso = builder.requestEmail().requestIdToken(cid).build()

            # -------------------------------------------------
            # Always use legacy intent flow (PyJNIus safe)
            # -------------------------------------------------
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
                Clock.schedule_once(lambda *_dt, msg=msg: cb(msg), 0)

    _start()
