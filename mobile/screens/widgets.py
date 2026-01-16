from __future__ import annotations

from kivy.core.window import Window
from kivy.properties import BooleanProperty
from kivy.uix.button import Button
from kivy.utils import platform


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
    pass

