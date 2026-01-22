from __future__ import annotations

import time

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

    def on_touch_down(self, touch):
        # Ignore mouse wheel scrolling etc.
        if getattr(touch, "is_mouse_scrolling", False):
            return super().on_touch_down(touch)

        if self.collide_point(*touch.pos):
            self._g_touch_uid = getattr(touch, "uid", None)
            self._g_start = (float(touch.x), float(touch.y))
            self._g_start_t = time.time()
            self._g_handled = False
            self._g_refreshed = False
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        out = super().on_touch_move(touch)

        if getattr(self, "_g_handled", False):
            return True

        if getattr(self, "_g_touch_uid", None) != getattr(touch, "uid", None):
            return out

        start = getattr(self, "_g_start", None)
        if not start:
            return out
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

        return out

    def on_touch_up(self, touch):
        # Reset gesture state.
        if getattr(self, "_g_touch_uid", None) == getattr(touch, "uid", None):
            self._g_touch_uid = None
            self._g_start = None
            self._g_handled = False
            self._g_refreshed = False
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

