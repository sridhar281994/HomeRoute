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
        # Never let logging break sign-in flow.
        pass


# ------------------------------------------------------------
# PUBLIC ENTRY POINT
# ------------------------------------------------------------
def google_sign_in(
    *,
    server_client_id: str,
    on_success: Callable[[str, dict[str, str]], None],
    on_error: Callable[[str], None],
) -> None:
    """
    Start Google Sign-In on Android and return a Google ID token.

    on_success(id_token, profile_dict)
    on_error(error_message)
    """
    _log("Starting Google Sign-In flow.")
    if platform != "android":
        _log("Platform is not Android; aborting.")
        Clock.schedule_once(
            lambda *_: on_error("Google Sign-In is only available on Android builds."),
            0,
        )
        return

    cid = (server_client_id or "").strip()
    if not cid:
        _log("Missing OAuth client ID; aborting.")
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
        from jnius import JavaClass, autoclass  # type: ignore
    except Exception as e:
        msg = f"Google Sign-In is unavailable in this build: {e}"
        _log(msg)
        Clock.schedule_once(lambda *_dt, msg=msg: on_error(msg), 0)
        return

    # Explicit PyJNIus bindings for overloaded static methods.
    # Use full JNI signatures to avoid "GoogleSignIn has no attribute" errors.
    class _GoogleSignIn(JavaClass):  # type: ignore[misc]
        __javaclass__ = "com/google/android/gms/auth/api/signin/GoogleSignIn"
        __javastaticmethods__ = [
            "getClient(Landroid/content/Context;Lcom/google/android/gms/auth/api/signin/GoogleSignInOptions;)"
            "Lcom/google/android/gms/auth/api/signin/GoogleSignInClient;",
            "getSignedInAccountFromIntent(Landroid/content/Intent;)Lcom/google/android/gms/tasks/Task;",
        ]

    global _bound
    _pending.clear()
    _pending["on_success"] = on_success
    _pending["on_error"] = on_error

    # ---------------------------------------------------------
    # Activity result binding (only once)
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
                Activity = autoclass("android.app.Activity")
                _log(
                    f"Activity result: req={request_code} "
                    f"result={result_code} data={'yes' if data is not None else 'no'}"
                )
                if int(result_code) != int(Activity.RESULT_OK):
                    fail("Google Sign-In cancelled.")
                    return True

                if data is None:
                    fail("Google Sign-In returned no data.")
                    return True

                _log("Parsing Google Sign-In intent.")
                task = _GoogleSignIn.getSignedInAccountFromIntent(data)

                # Prefer Task.getResult() with no args (avoids PyJNIus overload issues).
                account = task.getResult()

                id_token = str(account.getIdToken() or "").strip()
                if not id_token:
                    fail("Google Sign-In did not return an ID token (check OAuth client ID).")
                    return True
                _log("Google Sign-In returned ID token.")

                profile: dict[str, str] = {}
                try:
                    profile["email"] = str(account.getEmail() or "")
                except Exception:
                    profile["email"] = ""
                try:
                    profile["name"] = str(account.getDisplayName() or "")
                except Exception:
                    profile["name"] = ""
                try:
                    profile["given_name"] = str(account.getGivenName() or "")
                except Exception:
                    profile["given_name"] = ""
                try:
                    profile["family_name"] = str(account.getFamilyName() or "")
                except Exception:
                    profile["family_name"] = ""
                try:
                    profile["id"] = str(account.getId() or "")
                except Exception:
                    profile["id"] = ""

                cb = _pending.get("on_success")
                if cb:
                    Clock.schedule_once(lambda *_: cb(id_token, profile), 0)

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
            _log("Launching Google Sign-In intent.")

            GoogleSignInOptions = autoclass(
                "com.google.android.gms.auth.api.signin.GoogleSignInOptions"
            )

            # PyJNIus does not consistently expose Java inner classes as attributes,
            # so `GoogleSignInOptions.Builder(...)` can fail with:
            # "has no attribute 'Builder'". Load the inner class explicitly.
            GoogleSignInOptionsBuilder = autoclass(
                "com.google.android.gms.auth.api.signin.GoogleSignInOptions$Builder"
            )
            builder = GoogleSignInOptionsBuilder(GoogleSignInOptions.DEFAULT_SIGN_IN)
            gso = builder.requestEmail().requestIdToken(cid).build()

            client = _GoogleSignIn.getClient(act, gso)
            intent = client.getSignInIntent()
            act.startActivityForResult(intent, REQUEST_CODE_GOOGLE_SIGN_IN)

        except Exception as e:
            cb = _pending.get("on_error")
            if cb:
                msg = str(e) or "Failed to start Google Sign-In."
                _log(msg)
                Clock.schedule_once(lambda *_dt, msg=msg: cb(msg), 0)

    _start()
