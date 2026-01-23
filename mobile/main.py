from __future__ import annotations

import os

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.resources import resource_add_path, resource_find
from kivy.uix.screenmanager import FadeTransition, ScreenManager
from kivy.utils import platform

# Register custom widgets used in KV rules.
from screens.widgets import HoverButton, HoverToggleButton, AvatarButton  # noqa: F401

from screens.login_screen import LoginScreen
from screens.register_screen import RegisterScreen
from screens.reset_password_screen import ForgotPasswordScreen, ResetPasswordScreen
from screens.home_screen import HomeScreen
from screens.shell_screens import (
    MyPostsScreen,
    OwnerAddPropertyScreen,
    PropertyDetailScreen,
    SettingsScreen,
    SplashScreen,
    SubscriptionScreen,
    WelcomeScreen,
)


class QuickRentApp(App):
    title = "Flatnow.in"

    def build(self):
        # NOTE:
        # The real fix for "Clock: too much iteration" is to avoid creating many
        # large widget trees (and triggering lots of Label texture/layout work)
        # in a single frame. Do NOT "fix" by globally bumping max_iteration in
        # production; keep it opt-in for debugging only.
        try:
            env_max_it = (os.environ.get("KIVY_CLOCK_MAX_ITERATION") or "").strip()
            if env_max_it:
                Clock.max_iteration = int(env_max_it)
        except Exception:
            # Never crash due to a bad debug env var.
            pass

        # Android: keep focused inputs above the soft keyboard (OTP fields, etc).
        # This prevents the keyboard from covering TextInputs on smaller screens.
        try:
            if platform == "android":
                Window.softinput_mode = "below_target"
        except Exception:
            pass

        base_dir = os.path.dirname(__file__)
        resource_add_path(base_dir)
        resource_add_path(os.path.join(base_dir, "kv"))
        resource_add_path(os.path.join(base_dir, "assets"))
        self._register_fonts()
        kv_path = resource_find("kv/screens.kv") or os.path.join(base_dir, "kv", "screens.kv")
        Builder.load_file(kv_path)

        sm = ScreenManager(transition=FadeTransition())
        sm.add_widget(SplashScreen(name="splash"))
        sm.current = "splash"

        # Add remaining screens lazily across multiple frames.
        # IMPORTANT: use a *positive* delay between additions. Using 0 can cause
        # the Clock to process the whole chain in the same frame, leading to the
        # very "too much iteration" warning we're trying to avoid.
        pending: list[tuple[type, str]] = [
            (WelcomeScreen, "welcome"),
            (LoginScreen, "login"),
            (RegisterScreen, "register"),
            (ForgotPasswordScreen, "forgot_password"),
            (ResetPasswordScreen, "reset_password"),
            (HomeScreen, "home"),
            (MyPostsScreen, "my_posts"),
            (PropertyDetailScreen, "property_detail"),
            (SettingsScreen, "profile"),
            (SubscriptionScreen, "subscription"),
            (OwnerAddPropertyScreen, "owner_add_property"),
        ]

        # Add screens slowly enough that each addition gets its own rendered frame.
        # On slower devices/Windows builds, even "small" screens can trigger many
        # Label.texture_update + layout passes; too small a delay will still trip
        # Clock.max_iteration warnings.
        add_delay_s = 0.18

        def _add_next(_dt=0.0) -> None:
            if not pending:
                return
            cls, name = pending.pop(0)
            try:
                if not sm.has_screen(name):
                    sm.add_widget(cls(name=name))
            except Exception:
                # Never crash due to an eager screen build.
                pass
            if pending:
                Clock.schedule_once(_add_next, add_delay_s)

        Clock.schedule_once(_add_next, add_delay_s)

        return sm

    def _register_fonts(self) -> None:
        app_regular = resource_find("data/fonts/Roboto-Regular.ttf")
        app_bold = resource_find("data/fonts/Roboto-Bold.ttf")
        if app_regular:
            LabelBase.register(name="AppFont", fn_regular=app_regular, fn_bold=app_bold or app_regular)

        # Cursive tagline font (bundled with the app).
        cursive = resource_find("fonts/DancingScript.ttf")
        if cursive:
            # Use the same file for regular/bold; the font itself contains multiple weights.
            LabelBase.register(name="CursiveFont", fn_regular=cursive, fn_bold=cursive)

        emoji_candidates: list[str] = []
        env_path = (os.environ.get("EMOJI_FONT_PATH") or "").strip()
        if env_path:
            emoji_candidates.append(env_path)
        if platform == "android":
            emoji_candidates.extend(
                [
                    "/system/fonts/NotoColorEmoji.ttf",
                    "/system/fonts/EmojiCompat.ttf",
                ]
            )
        elif platform == "ios":
            emoji_candidates.append("/System/Library/Fonts/Apple Color Emoji.ttc")
        elif platform == "win":
            emoji_candidates.append(r"C:\Windows\Fonts\seguiemj.ttf")
        else:
            emoji_candidates.extend(
                [
                    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
                    "/usr/share/fonts/truetype/noto/NotoEmoji-Regular.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                ]
            )

        emoji_font = next((p for p in emoji_candidates if p and os.path.exists(p)), None)
        if emoji_font:
            LabelBase.register(name="EmojiFont", fn_regular=emoji_font)
        elif app_regular:
            LabelBase.register(name="EmojiFont", fn_regular=app_regular)


if __name__ == "__main__":
    QuickRentApp().run()

