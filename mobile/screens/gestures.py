from __future__ import annotations

import time

from kivy.core.window import Window
from kivy.metrics import dp


class GestureNavigationMixin:
    """
    Adds simple gesture navigation to Kivy Screens:
    - Horizontal swipe (from left edge) triggers back navigation.
    - Optional pull-to-refresh (swipe down when at top) if screen implements:
        - gesture_refresh() -> None
        - gesture_can_refresh() -> bool
    """

    # Tunables (dp so they scale with DPI)
    _SWIPE_BACK_EDGE = dp(48)  # must start near left edge
    _SWIPE_BACK_DX = dp(90)  # horizontal distance
    _SWIPE_BACK_DY_MAX = dp(70)  # vertical wiggle allowed

    _PULL_TO_REFRESH_DY = dp(110)
    _PULL_TO_REFRESH_DX_MAX = dp(80)

    def gesture_bind_window(self) -> None:
        """
        Bind gesture detection at Window level.

        This makes gestures work even when child widgets (TextInput/ScrollView)
        consume touch events before the Screen sees them.
        """
        try:
            if getattr(self, "_g_window_bound", False):
                return
            Window.bind(on_touch_down=self._gesture_window_down, on_touch_move=self._gesture_window_move, on_touch_up=self._gesture_window_up)
            self._g_window_bound = True
        except Exception:
            self._g_window_bound = False

    def gesture_unbind_window(self) -> None:
        try:
            if not getattr(self, "_g_window_bound", False):
                return
            Window.unbind(on_touch_down=self._gesture_window_down, on_touch_move=self._gesture_window_move, on_touch_up=self._gesture_window_up)
        except Exception:
            pass
        self._g_window_bound = False

    def _gesture_is_active_screen(self) -> bool:
        """
        Only run gestures for the currently visible Screen.
        """
        try:
            if not self.get_root_window():
                return False
        except Exception:
            return False
        try:
            mgr = getattr(self, "manager", None)
            name = getattr(self, "name", None)
            if mgr is not None and name:
                return str(getattr(mgr, "current", "") or "") == str(name)
        except Exception:
            pass
        return True

    def _gesture_track_down(self, touch) -> None:
        # Ignore mouse wheel scrolling etc.
        if getattr(touch, "is_mouse_scrolling", False):
            return
        try:
            if self.collide_point(*touch.pos):
                self._g_touch_uid = getattr(touch, "uid", None)
                self._g_start = (float(touch.x), float(touch.y))
                self._g_start_t = time.time()
                self._g_handled = False
                self._g_refreshed = False
        except Exception:
            return

    def _gesture_track_move(self, touch) -> bool:
        if getattr(self, "_g_handled", False):
            return True
        if getattr(self, "_g_touch_uid", None) != getattr(touch, "uid", None):
            return False

        start = getattr(self, "_g_start", None)
        if not start:
            return False
        sx, sy = start
        dx = float(touch.x) - float(sx)
        dy = float(touch.y) - float(sy)

        # Pull-to-refresh (only if screen opts in).
        if (not getattr(self, "_g_refreshed", False)) and dy > float(self._PULL_TO_REFRESH_DY) and abs(dx) < float(self._PULL_TO_REFRESH_DX_MAX):
            can_refresh = False
            try:
                can_refresh = bool(getattr(self, "gesture_can_refresh")())
            except Exception:
                can_refresh = False
            if can_refresh:
                self._g_refreshed = True
                try:
                    getattr(self, "gesture_refresh")()
                except Exception:
                    pass
                return True

        # Swipe-back (start from left edge, move right).
        if dx > float(self._SWIPE_BACK_DX) and abs(dy) < float(self._SWIPE_BACK_DY_MAX):
            # Only trigger when swipe begins near the left edge of the screen widget.
            try:
                if sx <= float(self.x + self._SWIPE_BACK_EDGE):
                    self._g_handled = True
                    self._gesture_back()
                    return True
            except Exception:
                pass

        return False

    def _gesture_track_up(self, touch) -> None:
        if getattr(self, "_g_touch_uid", None) == getattr(touch, "uid", None):
            self._g_touch_uid = None
            self._g_start = None
            self._g_handled = False
            self._g_refreshed = False

    def _gesture_window_down(self, _window, touch):
        if not self._gesture_is_active_screen():
            return False
        self._gesture_track_down(touch)
        return False

    def _gesture_window_move(self, _window, touch):
        if not self._gesture_is_active_screen():
            return False
        return bool(self._gesture_track_move(touch))

    def _gesture_window_up(self, _window, touch):
        if not self._gesture_is_active_screen():
            return False
        self._gesture_track_up(touch)
        return False

    def on_touch_down(self, touch):
        self._gesture_track_down(touch)
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        out = super().on_touch_move(touch)
        if self._gesture_track_move(touch):
            return True
        return out

    def on_touch_up(self, touch):
        self._gesture_track_up(touch)
        return super().on_touch_up(touch)

    def _gesture_back(self) -> None:
        """
        Back navigation target:
        - Prefer a screen-defined go_back()/back() handler.
        - Otherwise do nothing (safe default).
        """
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

