from __future__ import annotations

from kivy.core.window import Window
from kivy.animation import Animation
from kivy.properties import BooleanProperty, ListProperty, NumericProperty
from kivy.uix.button import Button
from kivy.uix.togglebutton import ToggleButton
from kivy.utils import platform
import math


class HoverBehavior:
    """
    Simple desktop-hover behavior for Kivy widgets.

    On mobile devices there is no cursor, so `hovered` will just remain False.
    """

    hovered = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.register_event_type("on_enter")
        self.register_event_type("on_leave")
        # Only bind hover on desktop platforms. On mobile, mouse_pos events can be noisy
        # and are unnecessary; they can also interfere with touch interactions on some devices.
        if platform not in {"android", "ios"}:
            Window.bind(mouse_pos=self._on_mouse_pos)

    def _on_mouse_pos(self, _window, pos):
        if not self.get_root_window():
            return
        try:
            inside = self.collide_point(*self.to_widget(*pos))
        except Exception:
            return
        if inside and not self.hovered:
            self.hovered = True
            self.dispatch("on_enter")
        elif not inside and self.hovered:
            self.hovered = False
            self.dispatch("on_leave")

    def on_enter(self, *args):
        pass

    def on_leave(self, *args):
        pass


class HoverButton(HoverBehavior, Button):
    """
    App-wide button with consistent interaction feedback:
    - Desktop: hover (via HoverBehavior)
    - Mobile/desktop: press scale + subtle shadow change + ripple
    """

    # Visual transform (used by KV via Scale instruction).
    ux_scale = NumericProperty(1.0)
    press_scale = NumericProperty(0.97)
    enable_scale_feedback = BooleanProperty(True)

    # Shadow controls (drawn in KV).
    shadow_alpha = NumericProperty(0.22)
    shadow_offset_y = NumericProperty(3.0)

    # Ripple state (drawn in KV).
    enable_ripple = BooleanProperty(True)
    ripple_alpha = NumericProperty(0.0)
    ripple_radius = NumericProperty(0.0)
    ripple_pos = ListProperty([0.0, 0.0])

    _pressed_inside = BooleanProperty(False)

    def _cancel_feedback_anims(self) -> None:
        Animation.cancel_all(self, "ux_scale", "shadow_offset_y", "shadow_alpha", "ripple_alpha", "ripple_radius")

    def _animate_press(self) -> None:
        self._cancel_feedback_anims()
        if self.enable_scale_feedback:
            Animation(ux_scale=float(self.press_scale), d=0.06, t="out_quad").start(self)
        # Slightly reduce shadow while pressed (gives "pressed in" feel).
        Animation(shadow_offset_y=1.0, shadow_alpha=0.14, d=0.06, t="out_quad").start(self)

    def _animate_release(self) -> None:
        if self.enable_scale_feedback:
            Animation(ux_scale=1.0, d=0.10, t="out_quad").start(self)
        Animation(shadow_offset_y=3.0, shadow_alpha=0.22, d=0.12, t="out_quad").start(self)

    def _start_ripple(self, touch) -> None:
        if not self.enable_ripple:
            return
        # Canvas coordinates match touch.pos (window/parent coords) for widget canvas.
        self.ripple_pos = [float(touch.pos[0]), float(touch.pos[1])]
        self.ripple_radius = 0.0
        self.ripple_alpha = 0.22

        # Ensure ripple expands beyond bounds even if touch near edge.
        max_r = max(self.width, self.height) * 1.15
        # Fallback if sizes are not ready yet.
        if not max_r:
            max_r = 240.0
        # Use diagonal for better coverage on wide buttons.
        max_r = max(max_r, math.hypot(self.width, self.height) * 0.65)

        Animation(ripple_radius=float(max_r), ripple_alpha=0.0, d=0.35, t="out_quad").start(self)

    def on_touch_down(self, touch):
        if self.disabled:
            return super().on_touch_down(touch)

        if self.collide_point(*touch.pos):
            self._pressed_inside = True
            self._animate_press()
            self._start_ripple(touch)

        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        was_pressed = bool(self._pressed_inside)
        self._pressed_inside = False

        out = super().on_touch_up(touch)

        # Always animate back if we handled the press (even if released outside).
        if was_pressed and not self.disabled:
            self._animate_release()
        return out

    def on_disabled(self, *_):
        # Reset visual state when disabled to avoid stuck transforms.
        self._pressed_inside = False
        self._cancel_feedback_anims()
        self.ux_scale = 1.0
        self.ripple_alpha = 0.0
        self.ripple_radius = 0.0


class HoverToggleButton(HoverBehavior, ToggleButton):
    """
    ToggleButton variant with the same interaction feedback as HoverButton.
    Useful for segmented controls (e.g., Owner/Customer role selection).
    """

    ux_scale = NumericProperty(1.0)
    press_scale = NumericProperty(0.97)
    enable_scale_feedback = BooleanProperty(True)

    shadow_alpha = NumericProperty(0.22)
    shadow_offset_y = NumericProperty(3.0)

    enable_ripple = BooleanProperty(True)
    ripple_alpha = NumericProperty(0.0)
    ripple_radius = NumericProperty(0.0)
    ripple_pos = ListProperty([0.0, 0.0])

    _pressed_inside = BooleanProperty(False)

    def _cancel_feedback_anims(self) -> None:
        Animation.cancel_all(self, "ux_scale", "shadow_offset_y", "shadow_alpha", "ripple_alpha", "ripple_radius")

    def _animate_press(self) -> None:
        self._cancel_feedback_anims()
        if self.enable_scale_feedback:
            Animation(ux_scale=float(self.press_scale), d=0.06, t="out_quad").start(self)
        Animation(shadow_offset_y=1.0, shadow_alpha=0.14, d=0.06, t="out_quad").start(self)

    def _animate_release(self) -> None:
        if self.enable_scale_feedback:
            Animation(ux_scale=1.0, d=0.10, t="out_quad").start(self)
        Animation(shadow_offset_y=3.0, shadow_alpha=0.22, d=0.12, t="out_quad").start(self)

    def _start_ripple(self, touch) -> None:
        if not self.enable_ripple:
            return
        self.ripple_pos = [float(touch.pos[0]), float(touch.pos[1])]
        self.ripple_radius = 0.0
        self.ripple_alpha = 0.22

        max_r = max(self.width, self.height) * 1.15
        if not max_r:
            max_r = 240.0
        max_r = max(max_r, math.hypot(self.width, self.height) * 0.65)

        Animation(ripple_radius=float(max_r), ripple_alpha=0.0, d=0.35, t="out_quad").start(self)

    def on_touch_down(self, touch):
        if self.disabled:
            return super().on_touch_down(touch)
        if self.collide_point(*touch.pos):
            self._pressed_inside = True
            self._animate_press()
            self._start_ripple(touch)
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        was_pressed = bool(self._pressed_inside)
        self._pressed_inside = False
        out = super().on_touch_up(touch)
        if was_pressed and not self.disabled:
            self._animate_release()
        return out

    def on_disabled(self, *_):
        self._pressed_inside = False
        self._cancel_feedback_anims()
        self.ux_scale = 1.0
        self.ripple_alpha = 0.0
        self.ripple_radius = 0.0

