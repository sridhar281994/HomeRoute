from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kivy.clock import Clock
from kivy.properties import BooleanProperty, DictProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen

from frontend_app.utils.api import (
    ApiError,
    api_get_property,
    api_get_property_contact,
    api_list_properties,
    api_subscription_status,
)
from frontend_app.utils.storage import clear_session, get_session, get_user


def _popup(title: str, msg: str) -> None:
    def _open(*_):
        popup = Popup(
            title=title,
            content=Label(text=str(msg)),
            size_hint=(0.78, 0.35),
            auto_dismiss=True,
        )
        popup.open()
        Clock.schedule_once(lambda _dt: popup.dismiss(), 2.2)

    Clock.schedule_once(_open, 0)


@dataclass
class PropertyCard:
    id: int
    title: str
    price: str
    location: str
    kind: str
    rent_sale: str


class SplashScreen(Screen):
    def on_enter(self, *args):
        # Small delay then continue to Welcome.
        Clock.schedule_once(lambda _dt: self._go_next(), 1.1)

    def _go_next(self):
        if self.manager:
            self.manager.current = "welcome"


class WelcomeScreen(Screen):
    pass


class HomeScreen(Screen):
    """
    Home / Property Feed + Search & Filters.
    """

    items = ListProperty([])
    query = StringProperty("")
    rent_sale = StringProperty("Any")
    property_type = StringProperty("Any")
    max_price = StringProperty("")

    is_loading = BooleanProperty(False)
    is_logged_in = BooleanProperty(False)

    def on_pre_enter(self, *args):
        # Gate buttons until user logs in.
        try:
            sess = get_session() or {}
            token = str(sess.get("token") or "")
            self.is_logged_in = bool(token)
        except Exception:
            self.is_logged_in = False
        Clock.schedule_once(lambda _dt: self.refresh(), 0)

    def refresh(self):
        if self.is_loading:
            return
        self.is_loading = True

        def work():
            try:
                data = api_list_properties(
                    q=(self.query or "").strip(),
                    rent_sale=(self.rent_sale or "").strip(),
                    property_type=(self.property_type or "").strip(),
                    max_price=(self.max_price or "").strip(),
                )
                cards: list[dict[str, Any]] = []
                for p in (data.get("items") or []):
                    cards.append(
                        {
                            "id": int(p.get("id") or 0),
                            "title": str(p.get("title") or "Property"),
                            "price": str(p.get("price_display") or p.get("price") or ""),
                            "location": str(p.get("location_display") or p.get("location") or ""),
                            "kind": str(p.get("property_type") or ""),
                            "rent_sale": str(p.get("rent_sale") or ""),
                        }
                    )

                def done(*_):
                    self.items = cards
                    # Render simple list into the KV container (no RecycleView dependency).
                    try:
                        container = self.ids.get("list_container")
                        if container is not None:
                            container.clear_widgets()
                            for c in cards:
                                title = c.get("title") or "Property"
                                meta = " • ".join(
                                    [
                                        x
                                        for x in [
                                            c.get("rent_sale"),
                                            c.get("kind"),
                                            c.get("price"),
                                            c.get("location"),
                                        ]
                                        if x
                                    ]
                                )
                                btn = Button(
                                    text=f"{title}\n{meta}",
                                    size_hint_y=None,
                                    height=88,
                                    halign="left",
                                    valign="middle",
                                )
                                btn.text_size = (btn.width, None)
                                pid = int(c.get("id") or 0)
                                btn.bind(on_release=lambda _b, pid=pid: self.open_property(pid))
                                container.add_widget(btn)
                    except Exception:
                        pass
                    self.is_loading = False

                Clock.schedule_once(done, 0)
            except ApiError as e:
                msg = str(e)
                Clock.schedule_once(lambda *_dt, msg=msg: _popup("Error", msg), 0)
                Clock.schedule_once(lambda *_: setattr(self, "is_loading", False), 0)

        from threading import Thread

        Thread(target=work, daemon=True).start()

    def open_property(self, property_id: int):
        if not self.manager:
            return
        detail: PropertyDetailScreen = self.manager.get_screen("property_detail")  # type: ignore[assignment]
        detail.load_property(property_id)
        self.manager.current = "property_detail"

    def go_profile(self):
        if not self.is_logged_in:
            _popup("Login required", "Please login to open Profile/Settings.")
            if self.manager:
                self.manager.current = "login"
            return
        if self.manager:
            self.manager.current = "profile"

    def go_owner(self):
        if not self.is_logged_in:
            _popup("Login required", "Please login to open Owner dashboard.")
            if self.manager:
                self.manager.current = "login"
            return
        u = get_user() or {}
        if (u.get("role") or "").lower() != "owner":
            _popup("Owner account required", "Please register/login as Owner to access this dashboard.")
            return
        if self.manager:
            self.manager.current = "owner_dashboard"

    def go_admin(self):
        # Removed from home page UI; keep method for backward KV compatibility.
        _popup("Not available", "Admin entry is hidden in the app UI.")


class PropertyDetailScreen(Screen):
    property_id = NumericProperty(0)
    property_data = DictProperty({})

    def load_property(self, property_id: int):
        self.property_id = int(property_id)
        self.property_data = {}

        def work():
            try:
                data = api_get_property(self.property_id)
                Clock.schedule_once(lambda *_: setattr(self, "property_data", data), 0)
            except ApiError as e:
                msg = str(e)
                Clock.schedule_once(lambda *_dt, msg=msg: _popup("Error", msg), 0)

        from threading import Thread

        Thread(target=work, daemon=True).start()

    def back(self):
        if self.manager:
            self.manager.current = "home"

    def unlock_contact(self):
        """
        Contact Unlock Flow:
        - If subscribed: fetch contact
        - Else: show Subscription page
        """
        sess = get_session() or {}
        if not (sess.get("token") or ""):
            _popup("Login required", "Please login to view contact details.")
            if self.manager:
                self.manager.current = "login"
            return

        def work():
            try:
                sub = api_subscription_status()
                active = bool((sub.get("status") or "").lower() == "active")
                if not active:
                    Clock.schedule_once(lambda *_: self._go_subscription(), 0)
                    return
                contact = api_get_property_contact(self.property_id)
                phone = contact.get("phone") or "N/A"
                email = contact.get("email") or "N/A"
                Clock.schedule_once(
                    lambda *_: _popup("Owner Contact", f"Phone: {phone}\nEmail: {email}"),
                    0,
                )
            except ApiError as e:
                msg = str(e)
                Clock.schedule_once(lambda *_dt, msg=msg: _popup("Error", msg), 0)

        from threading import Thread

        Thread(target=work, daemon=True).start()

    def _go_subscription(self):
        if self.manager:
            self.manager.current = "subscription"


class SubscriptionScreen(Screen):
    status_text = StringProperty("Unknown")

    def on_pre_enter(self, *args):
        self.refresh_status()

    def refresh_status(self):
        def work():
            try:
                sub = api_subscription_status()
                status = str(sub.get("status") or "inactive").capitalize()
                Clock.schedule_once(lambda *_: setattr(self, "status_text", status), 0)
            except ApiError as e:
                msg = str(e)
                Clock.schedule_once(lambda *_dt, msg=msg: _popup("Error", msg), 0)

        from threading import Thread

        Thread(target=work, daemon=True).start()

    def simulate_google_play_success(self):
        # Real payment is handled by Google Play Billing.
        _popup("Google Play Billing", "In production, Google completes payment.\nThis is a demo screen.")

    def back(self):
        if self.manager:
            self.manager.current = "property_detail"


class SettingsScreen(Screen):
    user_summary = StringProperty("")
    name_value = StringProperty("")
    phone_value = StringProperty("")
    email_value = StringProperty("")
    image_value = StringProperty("")
    locations_text = StringProperty("")
    subscription_status = StringProperty("Unknown")

    def on_pre_enter(self, *args):
        sess = get_session() or {}
        if not (sess.get("token") or ""):
            _popup("Login required", "Please login to open Settings.")
            if self.manager:
                self.manager.current = "login"
            return

        u = get_user() or {}
        # Do not show role in UI as requested.
        self.user_summary = f"{u.get('name') or 'User'}"
        self.name_value = str(u.get("name") or "")
        self.phone_value = str(u.get("phone") or "")
        self.email_value = str(u.get("email") or "")
        # Local-only fields (not yet stored on backend)
        self.image_value = str(u.get("image_url") or "")
        locs = u.get("locations") or []
        if isinstance(locs, list):
            self.locations_text = "\n".join(str(x) for x in locs if str(x).strip())
        else:
            self.locations_text = ""
        self.refresh_subscription()

    def save_settings(self):
        """
        Local profile editing (offline-friendly).
        Server sync can be added later with a /me endpoint.
        """
        u = get_user() or {}
        name = (self.ids.get("name_input").text or "").strip() if self.ids.get("name_input") else ""
        phone = (self.ids.get("phone_input").text or "").strip() if self.ids.get("phone_input") else ""
        email = (self.ids.get("email_input").text or "").strip() if self.ids.get("email_input") else ""
        image_url = (self.ids.get("image_url_input").text or "").strip() if self.ids.get("image_url_input") else ""
        raw_locations = (self.ids.get("locations_input").text or "") if self.ids.get("locations_input") else ""
        locations = [ln.strip() for ln in raw_locations.splitlines() if ln.strip()]

        # Update session user dict (local).
        u["name"] = name
        u["phone"] = phone
        u["email"] = email
        u["image_url"] = image_url
        u["locations"] = locations

        try:
            sess = get_session() or {}
            from frontend_app.utils.storage import set_session

            set_session(token=str(sess.get("token") or ""), user=u, remember=bool(sess.get("remember_me") or False))
            _popup("Saved", "Settings updated.")
        except Exception:
            _popup("Saved", "Settings updated (local).")

    def refresh_subscription(self):
        def work():
            try:
                sub = api_subscription_status()
                status = str(sub.get("status") or "inactive").capitalize()
                Clock.schedule_once(lambda *_: setattr(self, "subscription_status", status), 0)
            except ApiError as e:
                msg = str(e)
                Clock.schedule_once(lambda *_dt, msg=msg: _popup("Error", msg), 0)

        from threading import Thread

        Thread(target=work, daemon=True).start()

    def manage_subscription(self):
        if self.manager:
            self.manager.current = "subscription"

    def logout(self):
        clear_session()
        if self.manager:
            self.manager.current = "welcome"

    def go_back(self):
        if self.manager:
            self.manager.current = "home"


class OwnerDashboardScreen(Screen):
    owner_category = StringProperty("")

    def on_pre_enter(self, *args):
        u = get_user() or {}
        self.owner_category = str(u.get("owner_category") or "")

    def go_add(self):
        if self.manager:
            self.manager.current = "owner_add_property"

    def go_back(self):
        if self.manager:
            self.manager.current = "home"


class OwnerAddPropertyScreen(Screen):
    def submit_listing(self):
        _popup("Submitted", "Listing submitted for review (demo UI).")
        if self.manager:
            self.manager.current = "owner_dashboard"

    def go_back(self):
        if self.manager:
            self.manager.current = "owner_dashboard"


class AdminReviewScreen(Screen):
    def approve_demo(self):
        _popup("Approved", "Listing approved (demo UI).")

    def reject_demo(self):
        _popup("Rejected", "Listing rejected/flagged (demo UI).")

    def go_back(self):
        if self.manager:
            self.manager.current = "home"

