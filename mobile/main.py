from __future__ import annotations

from kivy.app import App
from kivy.lang import Builder
from kivy.uix.screenmanager import FadeTransition, ScreenManager

from screens.login_screen import LoginScreen
from screens.register_screen import RegisterScreen
from screens.reset_password_screen import ForgotPasswordScreen, ResetPasswordScreen
from screens.shell_screens import (
    HomeScreen,
    OwnerAddPropertyScreen,
    OwnerDashboardScreen,
    PropertyDetailScreen,
    SettingsScreen,
    SplashScreen,
    SubscriptionScreen,
    WelcomeScreen,
)


class PropertyDiscoveryApp(App):
    title = "Property Discovery"

    def build(self):
        Builder.load_file("kv/screens.kv")

        sm = ScreenManager(transition=FadeTransition())
        sm.add_widget(SplashScreen(name="splash"))
        sm.add_widget(WelcomeScreen(name="welcome"))
        sm.add_widget(LoginScreen(name="login"))
        sm.add_widget(RegisterScreen(name="register"))
        sm.add_widget(ForgotPasswordScreen(name="forgot_password"))
        sm.add_widget(ResetPasswordScreen(name="reset_password"))

        sm.add_widget(HomeScreen(name="home"))
        sm.add_widget(PropertyDetailScreen(name="property_detail"))
        sm.add_widget(SubscriptionScreen(name="subscription"))
        sm.add_widget(SettingsScreen(name="profile"))

        sm.add_widget(OwnerDashboardScreen(name="owner_dashboard"))
        sm.add_widget(OwnerAddPropertyScreen(name="owner_add_property"))

        sm.current = "splash"
        return sm


if __name__ == "__main__":
    PropertyDiscoveryApp().run()

