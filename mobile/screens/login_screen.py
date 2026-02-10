from threading import Thread

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.properties import BooleanProperty, NumericProperty
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen

from screens.gestures import GestureNavigationMixin
from frontend_app.utils.api import ApiError, api_login_google, api_login_request_otp, api_login_verify_otp
from frontend_app.utils.google_signin import google_sign_in
from frontend_app.utils.storage import get_remember_me, get_session, set_remember_me, set_session


def _safe_text(screen: Screen, wid: str, default: str = "") -> str:
    w = getattr(screen, "ids", {}).get(wid)
    return (w.text or "").strip() if w else default


def _popup(title: str, msg: str) -> None:
    def _open(*_):
        popup = Popup(
            title=title,
            content=Label(text=str(msg)),
            size_hint=(0.7, 0.3),
            auto_dismiss=True,
        )
        popup.open()
        Clock.schedule_once(lambda dt: popup.dismiss(), 2)

    Clock.schedule_once(_open, 0)


class LoginScreen(GestureNavigationMixin, Screen):
    # For auth screens, allow swipe-back from anywhere (not only left-edge).
    _SWIPE_BACK_EDGE = dp(10000)

    font_scale = NumericProperty(1.0)
    remember_me = BooleanProperty(False)
    is_processing = BooleanProperty(False)
    keyboard_padding = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        Clock.schedule_once(self._update_font_scale, 0)

    def on_remember_me(self, *_):
        # Persist preference immediately when toggled.
        try:
            set_remember_me(bool(self.remember_me))
        except Exception:
            pass

    def on_pre_enter(self, *args):
        # Clear old inputs and reset UI state on each entry.
        try:
            ids = getattr(self, "ids", {}) or {}
            for key in ("phone_input", "password_input", "otp_input"):
                w = ids.get(key)
                if w:
                    w.text = ""
                    try:
                        w.focus = False
                    except Exception:
                        pass

            btn = ids.get("request_otp_btn")
            if btn:
                btn.disabled = False
                btn.text = "Request OTP"

            vbtn = ids.get("verify_login_btn")
            if vbtn:
                vbtn.disabled = False
                vbtn.text = "Verify & Login"

            self.is_processing = False
            self.keyboard_padding = 0
        except Exception:
            pass

        # Sync checkbox with persisted preference.
        try:
            self.remember_me = bool(get_remember_me())
        except Exception:
            self.remember_me = False
        # Ensure soft keyboard does not hide OTP input.
        try:
            self._prev_softinput_mode = Window.softinput_mode
            Window.softinput_mode = "resize"
        except Exception:
            pass
        try:
            Window.bind(on_keyboard_height=self._on_keyboard_height)
        except Exception:
            pass
        # Make swipe-back work even when TextInput captures touch.
        try:
            self.gesture_bind_window()
        except Exception:
            pass

    def on_leave(self, *args):
        # Optionally clear on leave as well (prevents stale OTP/password).
        try:
            ids = getattr(self, "ids", {}) or {}
            for key in ("phone_input", "password_input", "otp_input"):
                w = ids.get(key)
                if w:
                    w.text = ""
                    try:
                        w.focus = False
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            Window.unbind(on_keyboard_height=self._on_keyboard_height)
        except Exception:
            pass
        try:
            if hasattr(self, "_prev_softinput_mode"):
                Window.softinput_mode = self._prev_softinput_mode
        except Exception:
            pass
        try:
            self.gesture_unbind_window()
        except Exception:
            pass
        return super().on_leave(*args)

    def on_size(self, *args):
        self._update_font_scale()

    def _on_keyboard_height(self, _window, height):
        try:
            h = float(height or 0)
        except Exception:
            return

        if h <= 0:
            self.keyboard_padding = 0
            return

        # Debounce small keyboard height changes (Android suggestion bar can jitter)
        # to avoid layout flicker while typing.
        try:
            last = float(getattr(self, "_last_kb_h", 0.0) or 0.0)
        except Exception:
            last = 0.0
        try:
            setattr(self, "_last_kb_h", h)
        except Exception:
            pass
        if last and abs(h - last) < dp(12):
            return

        # Push content above keyboard
        self.keyboard_padding = h + dp(20)

        w = self._focused_input()
        if w:
            self.scroll_to_field(w)

    def scroll_to_verify(self, *_):
        def _do(*_dt):
            try:
                sv = self.ids.get("login_scroll")
                btn = self.ids.get("verify_login_btn")
                if sv and btn:
                    sv.scroll_to(btn, padding=dp(200), animate=True)
            except Exception:
                pass

        Clock.schedule_once(_do, 0.1)
        Clock.schedule_once(_do, 0.3)

    def _update_font_scale(self, *_):
        width = self.width or Window.width or 1
        height = self.height or Window.height or 1
        width_ratio = width / 520.0
        height_ratio = height / 720.0
        self.font_scale = max(0.75, min(1.25, min(width_ratio, height_ratio)))

    def scroll_to_field(self, widget, *_):
        """
        Ensure a focused field stays above the soft keyboard.
        """
        def _do(*_dt):
            try:
                sv = self.ids.get("login_scroll")
                if sv is None or widget is None:
                    return
                sv.scroll_to(widget, padding=dp(160), animate=True)
            except Exception:
                return

        Clock.schedule_once(_do, 0.05)
        Clock.schedule_once(_do, 0.2)
        Clock.schedule_once(_do, 0.4)
        Clock.schedule_once(_do, 0.8)

    def _focused_input(self):
        for key in ("otp_input", "password_input", "phone_input"):
            try:
                w = (self.ids or {}).get(key)
            except Exception:
                w = None
            if w is not None and getattr(w, "focus", False):
                return w
        return None

    def _on_keyboard_height(self, _window, height):
        try:
            if float(height or 0) <= 0:
                return
        except Exception:
            return
        w = self._focused_input()
        if w is None:
            return
        self.scroll_to_field(w)

    # -----------------------
    # Navigation
    # -----------------------
    def go_back(self):
        # No Welcome screen wired in this repo; keep user on login.
        if self.manager and "welcome" in [s.name for s in self.manager.screens]:
            self.manager.current = "welcome"
        # else: no-op

    def open_forgot_password(self):
        if not self.manager:
            return
        fp = self.manager.get_screen("forgot_password")
        if hasattr(fp, "open_from"):
            fp.open_from(source_screen="login", title="Forgot Password")
        self.manager.current = "forgot_password"

    # -----------------------
    # Helpers
    # -----------------------
    def _read_identifier(self) -> str:
        return _safe_text(self, "phone_input")

    def _read_password(self) -> str:
        return _safe_text(self, "password_input")

    def _validate_identifier(self, identifier: str) -> bool:
        if not identifier:
            return False
        identifier = identifier.strip()
        if "@" in identifier and "." in identifier.split("@")[-1]:
            return True
        if identifier.isdigit() and 6 <= len(identifier) <= 15:
            return True
        return len(identifier) >= 3

    # -----------------------
    # Send OTP
    # -----------------------
    def send_otp_to_user(self):
        if self.is_processing:
            return
        self.is_processing = True
        identifier = self._read_identifier()
        password = self._read_password()

        if not self._validate_identifier(identifier):
            _popup("Error", "Enter a valid registered email or number.")
            self.is_processing = False
            return
        if len(password) < 4:
            _popup("Error", "Enter your password.")
            self.is_processing = False
            return

        btn = self.ids.get("request_otp_btn") if hasattr(self, "ids") else None
        btn_prev_text = getattr(btn, "text", None)

        def _set_btn_state(sending: bool) -> None:
            if not btn:
                return
            try:
                btn.disabled = bool(sending)
                if sending:
                    btn.text = "Sending OTP..."
                else:
                    btn.text = (btn_prev_text or "Request OTP")
            except Exception:
                return

        Clock.schedule_once(lambda *_: _set_btn_state(True), 0)

        def work():
            try:
                data = api_login_request_otp(identifier=identifier, password=password)
                Clock.schedule_once(
                    lambda *_: _popup("Success", data.get("message") or "OTP sent."),
                    0,
                )
            except ApiError as exc:
                # Don't close over `exc` inside a scheduled callback: Python clears
                # exception variables after the except block, causing NameError later.
                msg = str(exc)
                Clock.schedule_once(lambda *_dt, msg=msg: _popup("Error", msg), 0)
            except Exception as exc:
                # requests can throw connection/timeout errors that aren't ApiError.
                msg = str(exc) or "Failed to send OTP. Please check your network and try again."
                Clock.schedule_once(lambda *_dt, msg=msg: _popup("Error", msg), 0)
            finally:
                Clock.schedule_once(lambda *_: _set_btn_state(False), 0)
                Clock.schedule_once(lambda *_: setattr(self, "is_processing", False), 0)

        Thread(target=work, daemon=True).start()


    # -----------------------
    # Verify OTP + Login
    # -----------------------
    def verify_and_login(self):
        if self.is_processing:
            return
        self.is_processing = True
        identifier = self._read_identifier()
        password = self._read_password()
        otp = _safe_text(self, "otp_input")

        if not self._validate_identifier(identifier):
            _popup("Error", "Enter a valid registered email or number.")
            self.is_processing = False
            return
        if len(password) < 4:
            _popup("Error", "Enter your password.")
            self.is_processing = False
            return
        if not otp:
            _popup("Error", "Enter the OTP.")
            self.is_processing = False
            return

        # Disable the Verify button to prevent double-press race:
        # a second verify attempt can consume OTP then show "Invalid OTP"
        # even though the first attempt already logged in.
        verify_btn = self.ids.get("verify_login_btn") if hasattr(self, "ids") else None
        verify_prev_text = getattr(verify_btn, "text", None)

        def _set_verify_state(verifying: bool) -> None:
            if not verify_btn:
                return
            try:
                verify_btn.disabled = bool(verifying)
                verify_btn.text = "Verifying..." if verifying else (verify_prev_text or "Verify & Login")
            except Exception:
                return

        Clock.schedule_once(lambda *_: _set_verify_state(True), 0)

        def work():
            try:
                data = api_login_verify_otp(identifier=identifier, password=password, otp=otp)
                token = data.get("access_token")
                user = data.get("user") or {}
                if not token:
                    raise ApiError("Login failed.")

                set_remember_me(bool(self.remember_me))
                set_session(token=token, user=user, remember=bool(self.remember_me))

                def after(*_):
                    # Ensure top-bar avatar reflects the logged-in user immediately.
                    try:
                        from kivy.app import App as _App

                        a = _App.get_running_app()
                        if a and hasattr(a, "sync_user_badge"):
                            a.sync_user_badge()  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    if self.manager:
                        self.manager.current = "home"
                    _popup("Success", "Logged in.")

                Clock.schedule_once(after, 0)

            except ApiError as exc:
                msg = str(exc)
                Clock.schedule_once(lambda *_dt, msg=msg: _popup("Error", msg), 0)
            except Exception as exc:
                msg = str(exc) or "Login failed."
                Clock.schedule_once(lambda *_dt, msg=msg: _popup("Error", msg), 0)
            finally:
                Clock.schedule_once(lambda *_: _set_verify_state(False), 0)
                Clock.schedule_once(lambda *_: setattr(self, "is_processing", False), 0)

        Thread(target=work, daemon=True).start()

    # Admin login is done via the same OTP flow.

    # -----------------------
    # Google Login
    # -----------------------
    def google_login(self) -> None:
        """
        Google Sign-In (Android):
        - Launch Google account picker
        - Send ID token to backend (/auth/google)
        - Store session and navigate to home
        """
        server_client_id = ""

        def on_error(msg: str) -> None:
            _popup("Google Login", msg or "Google login failed.")

        def on_success(id_token: str, profile: dict[str, str]) -> None:
            def work():
                try:
                    data = api_login_google(id_token=id_token)
                    token = data.get("access_token")
                    user = data.get("user") or {}
                    if not token:
                        raise ApiError("Google login failed.")

                    # Persist remember-me preference consistently across auth methods.
                    set_remember_me(bool(self.remember_me))

                    sess = get_session() or {}
                    remember = bool(self.remember_me or sess.get("remember_me") or False)
                    set_session(token=str(token), user=dict(user), remember=remember)

                    def after(*_):
                        try:
                            from kivy.app import App as _App

                            a = _App.get_running_app()
                            if a and hasattr(a, "sync_user_badge"):
                                a.sync_user_badge()  # type: ignore[attr-defined]
                        except Exception:
                            pass
                        if self.manager:
                            self.manager.current = "home"
                        _popup("Success", f"Logged in as {user.get('name') or profile.get('email') or 'Google user'}.")

                    Clock.schedule_once(after, 0)
                except ApiError as e:
                    _popup("Google Login", str(e))
                except Exception as e:
                    _popup("Google Login", str(e) or "Network error. Please try again.")

            Thread(target=work, daemon=True).start()

        google_sign_in(server_client_id=server_client_id, on_success=on_success, on_error=on_error)

    def gesture_refresh_enabled(self) -> bool:
        return False
