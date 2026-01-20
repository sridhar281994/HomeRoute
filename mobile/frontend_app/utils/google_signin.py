from __future__ import annotations

from typing import Any, Callable

from kivy.clock import Clock
from kivy.utils import platform

REQUEST_CODE_GOOGLE_SIGN_IN = 4915

_bound = False
_pending: dict[str, Any] = {}


def _legacy_start_sign_in(*, act, gso, request_code: int, autoclass, on_error: Callable[[str], None]) -> None:
    """
    Fallback for older Play Services Auth versions where
    `GoogleSignIn.getClient(...)` is unavailable.
    """
    try:
        from jnius import PythonJavaClass, java_method  # type: ignore
    except Exception as e:
        raise RuntimeError(f"Legacy Google Sign-In unavailable: {e}") from e

    # Keep references alive to avoid GC while the flow is in progress.
    class _OnConnectionFailedListener(PythonJavaClass):  # type: ignore[misc]
        __javainterfaces__ = ["com/google/android/gms/common/api/GoogleApiClient$OnConnectionFailedListener"]

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
    GoogleApiClientBuilder = autoclass("com.google.android.gms.common.api.GoogleApiClient$Builder")

    listener = _OnConnectionFailedListener(on_error)
    client = GoogleApiClientBuilder(act).addApi(Auth.GOOGLE_SIGN_IN_API, gso).addOnConnectionFailedListener(listener).build()
    try:
        client.connect()
    except Exception:
        # Even if connect throws, older APIs may still provide an intent.
        pass

    # Store references to keep them alive.
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

    - server_client_id must be the OAuth "Web client" ID configured in Google Cloud console.
    - on_success(id_token, profile) is called on the Kivy main thread.
    - on_error(message) is called on the Kivy main thread.
    """
    if platform != "android":
        Clock.schedule_once(lambda *_: on_error("Google Sign-In is only available on Android builds."), 0)
        return

    cid = (server_client_id or "").strip()
    if not cid:
        Clock.schedule_once(
            lambda *_: on_error("Google Sign-In is not configured (missing GOOGLE_OAUTH_CLIENT_ID)."),
            0,
        )
        return

    # Defer heavy Android imports unless we're on Android.
    try:
        from android import activity  # type: ignore
        from android.runnable import run_on_ui_thread  # type: ignore
        from jnius import autoclass  # type: ignore
    except Exception as e:
        # Don't capture exception variable `e` in a lambda; Python clears it after except.
        msg = f"Google Sign-In is unavailable in this build: {e}"
        Clock.schedule_once(lambda *_dt, msg=msg: on_error(msg), 0)
        return

    global _bound
    _pending.clear()
    _pending["on_success"] = on_success
    _pending["on_error"] = on_error

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
                GoogleSignIn = autoclass("com.google.android.gms.auth.api.signin.GoogleSignIn")
                ApiException = autoclass("com.google.android.gms.common.api.ApiException")
                # New API path (preferred).
                try:
                    task = GoogleSignIn.getSignedInAccountFromIntent(data)
                    account = task.getResult(ApiException)
                except AttributeError:
                    # Legacy API path for older Play Services Auth.
                    Auth = autoclass("com.google.android.gms.auth.api.Auth")
                    result = Auth.GoogleSignInApi.getSignInResultFromIntent(data)
                    if result is None or (hasattr(result, "isSuccess") and not bool(result.isSuccess())):
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

    @run_on_ui_thread
    def _start() -> None:
        try:
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            act = PythonActivity.mActivity
            GoogleSignInOptions = autoclass("com.google.android.gms.auth.api.signin.GoogleSignInOptions")
            GoogleSignIn = autoclass("com.google.android.gms.auth.api.signin.GoogleSignIn")

            builder = GoogleSignInOptions.Builder(GoogleSignInOptions.DEFAULT_SIGN_IN)
            gso = builder.requestEmail().requestIdToken(cid).build()
            # Prefer the modern GoogleSignInClient flow.
            try:
                # Using application context can avoid some overload resolution issues in PyJNIus.
                ctx = act.getApplicationContext()
                client = GoogleSignIn.getClient(ctx, gso)
                intent = client.getSignInIntent()
                act.startActivityForResult(intent, REQUEST_CODE_GOOGLE_SIGN_IN)
            except AttributeError:
                # Fallback for older Play Services Auth where getClient() isn't present.
                _legacy_start_sign_in(
                    act=act,
                    gso=gso,
                    request_code=REQUEST_CODE_GOOGLE_SIGN_IN,
                    autoclass=autoclass,
                    on_error=lambda msg: Clock.schedule_once(lambda *_dt, msg=msg: on_error(msg), 0),
                )
        except Exception as e:
            cb = _pending.get("on_error")
            if cb:
                msg = str(e) or "Failed to start Google Sign-In."
                Clock.schedule_once(lambda *_dt, msg=msg: cb(msg), 0)

    _start()

