from __future__ import annotations

import time

from kivy.core.window import Window
from kivy.factory import Factory
from kivy.metrics import dp
from kivy.uix.dropdown import DropDown
from kivy.uix.label import Label
from kivy.clock import Clock


class GestureNavigationMixin:
    """
    Adds simple gesture navigation to Kivy Screens:
    - Horizontal swipe (left ↔ right) triggers back navigation.
    - Vertical swipe down triggers pull-to-refresh with visual indicator.
    """

    # Tunables
    _SWIPE_BACK_DX = dp(70)          # horizontal distance
    _SWIPE_BACK_DY_MAX = dp(40)      # vertical wiggle allowed

    _PULL_TO_REFRESH_DY = dp(75)
    _PULL_TO_REFRESH_DX_MAX = dp(120)
    _REFRESH_START_DY = dp(12)       # minimum downward movement to show indicator
    _VERTICAL_DOMINANCE = 1.3        # dy must dominate dx

    # Velocity thresholds (px/sec)
    _MIN_SWIPE_VELOCITY = 900.0

    # Lifecycle guards
    _gesture_active = False
    _gesture_destroyed = False

    # ------------------------------------------------------------------
    # Refresh gate
    # ------------------------------------------------------------------
    def gesture_can_refresh(self) -> bool:
        try:
            if bool(getattr(self, "is_loading", False)):
                return False
        except Exception:
            pass

        sv = None
        try:
            ids = getattr(self, "ids", {}) or {}
            for key in ("feed_scroll", "my_posts_scroll"):
                if key in ids:
                    sv = ids.get(key)
                    break
        except Exception:
            sv = None

        if sv is None:
            return True  # ✅ allow refresh if scrollview not found (desktop safety)

        try:
            y = float(getattr(sv, "scroll_y", 0.0) or 0.0)
            # ✅ Relax threshold — real devices rarely hit 1.0 exactly
            return y >= 0.85
        except Exception:
            return True

    def gesture_refresh(self) -> None:
        try:
            if hasattr(self, "refresh"):
                getattr(self, "refresh")()
                return
        except Exception:
            pass

        try:
            if hasattr(self, "refresh_status"):
                getattr(self, "refresh_status")()
                return
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Touch helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _gesture_get_touch(*args):
        if not args:
            return None
        if len(args) >= 2:
            return args[-1]
        return args[0]

    # ------------------------------------------------------------------
    # Touch tracking
    # ------------------------------------------------------------------
    def _gesture_track_down(self, *args) -> None:
        touch = self._gesture_get_touch(*args)
        if not getattr(self, "_gesture_active", False):
            return
        if touch is None:
            return

        if getattr(touch, "is_mouse_scrolling", False):
            return

        try:
            self._g_touch_uid = getattr(touch, "uid", None)
            self._g_start = (float(touch.x), float(touch.y))
            self._g_last = (float(touch.x), float(touch.y))
            self._g_start_t = time.time()
            self._g_handled = False
            self._g_refreshed = False
            self._g_refresh_ready = False  # ✅ ADD THIS
        except Exception:
            return

    def _show_refresh_indicator(self) -> None:
        try:
            if getattr(self, "_g_refresh_label", None):
                return

            lbl = Label(
                text="Release to refresh",
                size_hint=(None, None),
                size=(dp(260), dp(44)),
                pos_hint={"center_x": 0.5, "top": 0.98},
                color=(1, 1, 1, 1),
            )

            self._g_refresh_label = lbl

            # ✅ Add directly to the Screen (always visible)
            self.add_widget(lbl)

            print("[GESTURE] Refresh indicator shown")

        except Exception as e:
            print("[GESTURE] Indicator error:", e)

    def _hide_refresh_indicator(self) -> None:
        try:
            lbl = getattr(self, "_g_refresh_label", None)
            if lbl and lbl.parent:
                lbl.parent.remove_widget(lbl)
            self._g_refresh_label = None
        except Exception:
            self._g_refresh_label = None

    def _gesture_track_move(self, *args) -> bool:
        touch = self._gesture_get_touch(*args)
        if not getattr(self, "_gesture_active", False):
            return False
        if touch is None:
            return False

        if getattr(self, "_g_handled", False):
            return True

        if getattr(self, "_g_touch_uid", None) != getattr(touch, "uid", None):
            return False

        start = getattr(self, "_g_start", None)
        if not start:
            return False

        sx, sy = start
        cx, cy = float(touch.x), float(touch.y)

        dx = cx - sx
        dy = cy - sy

        abs_dx = abs(dx)
        abs_dy = abs(dy)

        # ---------------------------------------------------
        # Vertical swipe down → REFRESH (ARM ONLY)
        # Kivy: dragging DOWN produces NEGATIVE dy
        # ---------------------------------------------------
        pull_down = -dy  # convert downward movement to positive value

        if (
                self.gesture_refresh_enabled()
                and pull_down >= float(self._REFRESH_START_DY)
                and abs_dy > abs_dx * self._VERTICAL_DOMINANCE
        ):

            print("[GESTURE] PULL DOWN:", pull_down)

            try:
                can_refresh = bool(self.gesture_can_refresh())
            except Exception:
                can_refresh = False

            if can_refresh:
                # ✅ Show indicator ONCE and keep it visible
                self._show_refresh_indicator()

                # ✅ Arm refresh — DO NOT trigger here
                if pull_down >= float(self._PULL_TO_REFRESH_DY):
                    self._g_refresh_ready = True

                # Block ScrollView while pulling
                return True

        # ---------------------------------------------------
        # Horizontal swipe → BACK
        # ---------------------------------------------------
        if (
                abs_dx > float(self._SWIPE_BACK_DX)
                and abs_dy < float(self._SWIPE_BACK_DY_MAX)
        ):
            self._g_handled = True
            self._hide_refresh_indicator()
            self._gesture_back()
            return True

        return False

    def _gesture_track_up(self, *args) -> None:
        touch = self._gesture_get_touch(*args)
        if not getattr(self, "_gesture_active", False):
            return
        if touch is None:
            return

        if getattr(self, "_g_touch_uid", None) == getattr(touch, "uid", None):

            # ✅ Trigger refresh ONLY after release
            if getattr(self, "_g_refresh_ready", False):
                print("[GESTURE] REFRESH TRIGGERED (ON RELEASE)")
                try:
                    self.gesture_refresh()
                except Exception:
                    pass

            self._g_touch_uid = None
            self._g_start = None
            self._g_last = None
            self._g_handled = False
            self._g_refreshed = False
            self._g_refresh_ready = False
            self._hide_refresh_indicator()

    # ------------------------------------------------------------------
    # Normal widget touch flow
    # ------------------------------------------------------------------
    def on_touch_down(self, touch):
        if self._gesture_active:
            self._gesture_track_down(touch)
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self._gesture_active:
            if self._gesture_track_move(touch):
                return True  # ✅ consume event (stop ScrollView)
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if self._gesture_active:
            self._gesture_track_up(touch)
        return super().on_touch_up(touch)

    # ------------------------------------------------------------------
    # Back navigation target
    # ------------------------------------------------------------------
    def _gesture_back(self) -> None:
        def _do_back(_dt):
            try:
                if hasattr(self, "go_back"):
                    getattr(self, "go_back")()
                    return
            except Exception:
                pass
            try:
                if hasattr(self, "back"):
                    getattr(self, "back")()
                    return
            except Exception:
                pass

        try:
            Clock.schedule_once(_do_back, 0)
        except Exception:
            pass

    # -----------------------
    # Hamburger menu
    # -----------------------
    def open_hamburger_menu(self, anchor_widget) -> None:
        try:
            dd = getattr(self, "_hamburger_dd", None)
        except Exception:
            dd = None

        if dd is None:
            dd = DropDown(auto_width=False, width=dp(220))

            def _mk_item(label: str, action: str) -> None:
                try:
                    btn = Factory.AppButton(text=label)
                except Exception:
                    btn = Factory.Button(text=label)
                btn.size_hint_y = None
                btn.height = dp(44)
                btn.bind(on_release=lambda *_: (dd.dismiss(), self._hamburger_navigate(action)))
                dd.add_widget(btn)

            _mk_item("Home", "home")
            _mk_item("My Posts", "my_posts")
            _mk_item("Settings", "profile")
            _mk_item("Publish Ad", "owner_add_property")
            _mk_item("Subscription", "subscription")
            _mk_item("Logout", "logout")

            try:
                setattr(self, "_hamburger_dd", dd)
            except Exception:
                pass

        try:
            dd.open(anchor_widget)
        except Exception:
            return

    def _hamburger_navigate(self, action: str) -> None:
        action = str(action or "").strip()
        mgr = getattr(self, "manager", None)
        if not mgr:
            return

        if action == "logout":
            try:
                from frontend_app.utils.storage import clear_session
                clear_session()
            except Exception:
                pass
            try:
                from kivy.app import App as _App

                a = _App.get_running_app()
                if a and hasattr(a, "sync_user_badge"):
                    a.sync_user_badge()  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                mgr.current = "login"
            except Exception:
                pass
            return

        if action == "owner_add_property":
            try:
                scr = mgr.get_screen("owner_add_property")
                if hasattr(scr, "start_new"):
                    scr.start_new()
            except Exception:
                pass

        try:
            mgr.current = action
        except Exception:
            return

    # ------------------------------------------------------------------
    # Window-level binding
    # ------------------------------------------------------------------
    def gesture_bind_window(self) -> None:
        # ✅ No Window binding anymore — enable local widget gestures
        self._gesture_active = True
        self._gesture_destroyed = False

    def gesture_unbind_window(self) -> None:
        self._gesture_active = False
        self._gesture_destroyed = True

    # ------------------------------------------------------------------
    # Refresh enable flag (override per screen)
    # ------------------------------------------------------------------
    def gesture_refresh_enabled(self) -> bool:
        """
        Override in screens where pull-to-refresh is allowed.
        Default: disabled.
        """
        return False
