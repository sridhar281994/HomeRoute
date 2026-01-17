from __future__ import annotations

import os

from kivy.app import App
from kivy.core.text import LabelBase
from kivy.lang import Builder
from kivy.resources import resource_find
from kivy.uix.screenmanager import FadeTransition, ScreenManager
from kivy.utils import platform

# Register custom widgets used in KV rules.
from screens.widgets import HoverButton, HoverToggleButton  # noqa: F401

from screens.login_screen import LoginScreen
from screens.register_screen import RegisterScreen
from screens.reset_password_screen import ForgotPasswordScreen, ResetPasswordScreen
from screens.shell_screens import (
    HomeScreen,
    MyPostsScreen,
    OwnerAddPropertyScreen,
    OwnerDashboardScreen,
    PropertyDetailScreen,
    SettingsScreen,
    SplashScreen,
    SubscriptionScreen,
    WelcomeScreen,
)


class QuickRentApp(App):
    title = "QuickRent"

    def build(self):
        self._register_fonts()
        Builder.load_file("kv/screens.kv")

        sm = ScreenManager(transition=FadeTransition())
        sm.add_widget(SplashScreen(name="splash"))
        sm.add_widget(WelcomeScreen(name="welcome"))
        sm.add_widget(LoginScreen(name="login"))
        sm.add_widget(RegisterScreen(name="register"))
        sm.add_widget(ForgotPasswordScreen(name="forgot_password"))
        sm.add_widget(ResetPasswordScreen(name="reset_password"))

        sm.add_widget(HomeScreen(name="home"))
        sm.add_widget(MyPostsScreen(name="my_posts"))
        sm.add_widget(PropertyDetailScreen(name="property_detail"))
        sm.add_widget(SubscriptionScreen(name="subscription"))
        sm.add_widget(SettingsScreen(name="profile"))

        sm.add_widget(OwnerDashboardScreen(name="owner_dashboard"))
        sm.add_widget(OwnerAddPropertyScreen(name="owner_add_property"))

        sm.current = "splash"
        return sm

    def _register_fonts(self) -> None:
        app_regular = resource_find("data/fonts/Roboto-Regular.ttf")
        app_bold = resource_find("data/fonts/Roboto-Bold.ttf")
        if app_regular:
            LabelBase.register(name="AppFont", fn_regular=app_regular, fn_bold=app_bold or app_regular)

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

