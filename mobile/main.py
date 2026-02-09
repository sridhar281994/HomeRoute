from __future__ import annotations

import os

from kivy.app import App
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.properties import StringProperty
from kivy.resources import resource_add_path, resource_find
from kivy.uix.screenmanager import FadeTransition, ScreenManager
from kivy.utils import platform

# Register custom widgets used in KV rules.
from screens.widgets import AvatarButton, HoverButton, HoverToggleButton, MobileTopBar  # noqa: F401

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
    # Shared user badge for all screens (used by MobileTopBar in KV).
    user_initial = StringProperty("U")
    user_avatar_url = StringProperty("")

    def build(self):
        base_dir = os.path.dirname(__file__)
        resource_add_path(base_dir)
        resource_add_path(os.path.join(base_dir, "kv"))
        resource_add_path(os.path.join(base_dir, "assets"))
        self._register_fonts()
        kv_path = resource_find("kv/screens.kv") or os.path.join(base_dir, "kv", "screens.kv")
        Builder.load_file(kv_path)

        sm = ScreenManager()
        sm.add_widget(SplashScreen(name="splash"))
        sm.add_widget(WelcomeScreen(name="welcome"))
        sm.add_widget(LoginScreen(name="login"))
        sm.add_widget(RegisterScreen(name="register"))
        sm.add_widget(ForgotPasswordScreen(name="forgot_password"))
        sm.add_widget(ResetPasswordScreen(name="reset_password"))

        sm.add_widget(HomeScreen(name="home"))
        sm.add_widget(MyPostsScreen(name="my_posts"))
        sm.add_widget(PropertyDetailScreen(name="property_detail"))
        sm.add_widget(SettingsScreen(name="profile"))
        sm.add_widget(SubscriptionScreen(name="subscription"))

        sm.add_widget(OwnerAddPropertyScreen(name="owner_add_property"))

        sm.current = "splash"

        # ✅ Intercept Android BACK button / gesture
        try:
            Window.bind(on_key_down=self._on_android_back)
        except Exception:
            pass

        return sm

    def on_start(self):
        # Keep top-bar avatar consistent across screens.
        try:
            self.sync_user_badge()
        except Exception:
            pass
        try:
            if self.root is not None:
                self.root.bind(current=lambda *_: self.sync_user_badge())
        except Exception:
            pass

    def sync_user_badge(self) -> None:
        """
        Refresh `user_initial` + `user_avatar_url` from persisted session.
        Called after login/profile updates and on screen changes.
        """
        try:
            from frontend_app.utils.storage import get_user

            u = get_user() or {}
        except Exception:
            u = {}

        name = str(
            u.get("name")
            or u.get("full_name")
            or u.get("username")
            or u.get("email")
            or u.get("phone")
            or ""
        ).strip()
        self.user_initial = (name[0].upper() if name else "U")

        try:
            # `set_session()` already normalizes relative URLs to absolute when possible.
            avatar = str(u.get("profile_image_url") or "").strip()
            self.user_avatar_url = avatar
        except Exception:
            self.user_avatar_url = ""

    # ------------------------------------------------------------------
    # Android BACK interception (maps to screen.back())
    # ------------------------------------------------------------------
    def _on_android_back(self, window, key, *args):
        """
        Intercept Android system back button / gesture and route it
        to the current screen's back() or go_back() handler instead
        of closing the app.
        """
        # 27 = ESC (desktop), 1001 = Android back on some devices
        if key not in (27, 1001):
            return False

        try:
            sm = self.root
            if not sm:
                return False

            screen = sm.current_screen
            if not screen:
                return False

            # Only allow the OS to exit the app from the Home screen.
            # For all other screens, consume BACK and route to in-app navigation.
            try:
                if getattr(screen, "name", "") == "home":
                    return False
            except Exception:
                pass

            # Prefer screen.back()
            if hasattr(screen, "back"):
                screen.back()
                return True

            # Fallback: screen.go_back()
            if hasattr(screen, "go_back"):
                screen.go_back()
                return True

        except Exception:
            pass

        # Returning False allows OS default (exit app)
        return False

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
