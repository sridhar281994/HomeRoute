from __future__ import annotations

from typing import Any, Callable

from kivy.clock import Clock
from kivy.utils import platform

REQUEST_CODE_GOOGLE_SIGN_IN = 4915

_bound = False
_pending: dict[str, Any] = {}


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
        Clock.schedule_once(lambda *_: on_error(f"Google Sign-In is unavailable in this build: {e}"), 0)
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
                task = GoogleSignIn.getSignedInAccountFromIntent(data)
                account = task.getResult(ApiException)
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
            client = GoogleSignIn.getClient(act, gso)

            intent = client.getSignInIntent()
            act.startActivityForResult(intent, REQUEST_CODE_GOOGLE_SIGN_IN)
        except Exception as e:
            cb = _pending.get("on_error")
            if cb:
                Clock.schedule_once(lambda *_: cb(str(e) or "Failed to start Google Sign-In."), 0)

    _start()

