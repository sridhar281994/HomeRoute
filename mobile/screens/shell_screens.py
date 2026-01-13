from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from kivy.clock import Clock
from kivy.properties import BooleanProperty, DictProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen

from screens.widgets import HoverButton
from frontend_app.utils.api import (
    ApiError,
    api_get_property,
    api_get_property_contact,
    api_list_properties,
    api_me,
    api_me_change_email_request_otp,
    api_me_change_email_verify,
    api_me_change_phone_request_otp,
    api_me_change_phone_verify,
    api_me_delete,
    api_me_update,
    api_me_upload_profile_image,
    api_meta_categories,
    api_subscription_status,
)
from frontend_app.utils.storage import clear_session, get_session, get_user, set_session


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
        # Small delay then continue to Welcome or Home (if already logged in).
        Clock.schedule_once(lambda _dt: self._go_next(), 0.9)

    def _go_next(self):
        if not self.manager:
            return
        try:
            sess = get_session() or {}
            token = str(sess.get("token") or "")
            self.manager.current = "home" if token else "welcome"
        except Exception:
            self.manager.current = "welcome"


class WelcomeScreen(Screen):
    def on_pre_enter(self, *args):
        # If user is already authenticated, skip Welcome.
        if not self.manager:
            return
        try:
            sess = get_session() or {}
            token = str(sess.get("token") or "")
            if token:
                self.manager.current = "home"
        except Exception:
            return


class HomeScreen(Screen):
    """
    Home / Property Feed + Search & Filters.
    """

    items = ListProperty([])
    query = StringProperty("")
    need_category = StringProperty("Any")
    need_values = ListProperty(["Any"])
    rent_sale = StringProperty("Any")
    property_type = StringProperty("Any")
    max_price = StringProperty("")
    bg_image = StringProperty("")

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

        # Optional fabulous background image (local asset).
        # If missing, KV keeps the glossy orange base.
        try:
            here = os.path.dirname(os.path.dirname(__file__))  # .../mobile/screens -> .../mobile
            candidate = os.path.join(here, "assets", "home_bg.jpg")
            self.bg_image = "assets/home_bg.jpg" if os.path.exists(candidate) else ""
        except Exception:
            self.bg_image = ""

        # Load customer "need" categories (non-fatal if offline).
        self._load_need_categories()

        Clock.schedule_once(lambda _dt: self.refresh(), 0)

    def _load_need_categories(self):
        def work():
            try:
                data = api_meta_categories()
                cats = data.get("categories") or []
                values: list[str] = ["Any"]
                for g in cats:
                    group = str((g or {}).get("group") or "").strip()
                    items = (g or {}).get("items") or []
                    for it in items:
                        label = str(it or "").strip()
                        if not label:
                            continue
                        # Keep labels unique + understandable without optgroup support.
                        values.append(f"{group} — {label}" if group else label)

                # De-dup while keeping order
                seen: set[str] = set()
                deduped = []
                for v in values:
                    if v in seen:
                        continue
                    seen.add(v)
                    deduped.append(v)

                Clock.schedule_once(lambda *_: setattr(self, "need_values", deduped), 0)
            except Exception:
                # Keep default values.
                return

        from threading import Thread

        Thread(target=work, daemon=True).start()

    def refresh(self):
        if self.is_loading:
            return
        self.is_loading = True

        def work():
            try:
                need = (self.need_category or "").strip()
                # If values are "Group — Label", use only the label for matching.
                if "—" in need:
                    need = need.split("—", 1)[1].strip()
                q = (self.query or "").strip()
                combined_q = " ".join([x for x in [need if need and need.lower() != "any" else "", q] if x]).strip()
                data = api_list_properties(
                    q=combined_q,
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
                                btn = HoverButton(
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
    role_value = StringProperty("")
    profile_image_url = StringProperty("")
    subscription_status = StringProperty("Unknown")

    def on_pre_enter(self, *args):
        sess = get_session() or {}
        if not (sess.get("token") or ""):
            _popup("Login required", "Please login to open Settings.")
            if self.manager:
                self.manager.current = "login"
            return

        # Load latest profile from server.
        u_local = get_user() or {}
        self._apply_user(u_local)
        self._refresh_profile_from_server()
        self.refresh_subscription()

    def _apply_user(self, u: dict[str, Any]) -> None:
        self.user_summary = f"{u.get('name') or 'User'}"
        self.name_value = str(u.get("name") or "")
        self.phone_value = str(u.get("phone") or "")
        self.email_value = str(u.get("email") or "")
        self.role_value = str(u.get("role") or "")
        self.profile_image_url = str(u.get("profile_image_url") or "")

        # Keep inputs in sync if KV ids exist.
        try:
            if self.ids.get("name_input"):
                self.ids["name_input"].text = self.name_value
            if self.ids.get("phone_current"):
                self.ids["phone_current"].text = self.phone_value
            if self.ids.get("email_current"):
                self.ids["email_current"].text = self.email_value
            if self.ids.get("role_display"):
                self.ids["role_display"].text = "Owner" if self.role_value.lower() == "owner" else "Customer"
        except Exception:
            pass

    def _refresh_profile_from_server(self):
        from threading import Thread

        def work():
            try:
                data = api_me()
                u = data.get("user") or {}
                sess = get_session() or {}
                set_session(token=str(sess.get("token") or ""), user=u, remember=bool(sess.get("remember_me") or False))
                Clock.schedule_once(lambda *_: self._apply_user(u), 0)
            except Exception:
                return

        Thread(target=work, daemon=True).start()

    def save_name(self):
        name = (self.ids.get("name_input").text or "").strip() if self.ids.get("name_input") else ""
        if not name:
            _popup("Error", "Name is required.")
            return

        from threading import Thread

        def work():
            try:
                data = api_me_update(name=name)
                u = data.get("user") or {}
                sess = get_session() or {}
                set_session(token=str(sess.get("token") or ""), user=u, remember=bool(sess.get("remember_me") or False))
                Clock.schedule_once(lambda *_: self._apply_user(u), 0)
                Clock.schedule_once(lambda *_: _popup("Saved", "Name updated."), 0)
            except ApiError as e:
                msg = str(e)
                Clock.schedule_once(lambda *_dt, msg=msg: _popup("Error", msg), 0)

        Thread(target=work, daemon=True).start()

    def open_image_picker(self):
        chooser = FileChooserListView(path=os.path.expanduser("~"), filters=["*.png", "*.jpg", "*.jpeg", "*.webp"])

        def do_upload(_btn):
            if not chooser.selection:
                _popup("Select image", "Please pick an image file.")
                return
            fp = chooser.selection[0]
            popup.dismiss()
            self.upload_profile_image(fp)

        buttons = BoxLayout(size_hint_y=None, height=48, spacing=8, padding=[8, 8])
        btn_upload = HoverButton(text="Upload", background_color=(0.3, 0.8, 0.4, 1))
        btn_cancel = HoverButton(text="Cancel", background_color=(0.7, 0.2, 0.2, 1))
        buttons.add_widget(btn_cancel)
        buttons.add_widget(btn_upload)

        root = BoxLayout(orientation="vertical", spacing=8, padding=8)
        root.add_widget(chooser)
        root.add_widget(buttons)

        popup = Popup(title="Choose Profile Image", content=root, size_hint=(0.9, 0.9), auto_dismiss=False)
        btn_cancel.bind(on_release=lambda *_: popup.dismiss())
        btn_upload.bind(on_release=do_upload)
        popup.open()

    def upload_profile_image(self, file_path: str):
        from threading import Thread

        def work():
            try:
                data = api_me_upload_profile_image(file_path=file_path)
                u = data.get("user") or {}
                sess = get_session() or {}
                set_session(token=str(sess.get("token") or ""), user=u, remember=bool(sess.get("remember_me") or False))
                Clock.schedule_once(lambda *_: self._apply_user(u), 0)
                Clock.schedule_once(lambda *_: _popup("Saved", "Profile image updated."), 0)
            except ApiError as e:
                msg = str(e)
                Clock.schedule_once(lambda *_dt, msg=msg: _popup("Error", msg), 0)

        Thread(target=work, daemon=True).start()

    def request_email_otp(self):
        new_email = (self.ids.get("new_email_input").text or "").strip() if self.ids.get("new_email_input") else ""
        if not new_email:
            _popup("Error", "Enter new email.")
            return

        from threading import Thread

        def work():
            try:
                data = api_me_change_email_request_otp(new_email=new_email)
                Clock.schedule_once(lambda *_: _popup("OTP", data.get("message") or "OTP sent."), 0)
            except ApiError as e:
                msg = str(e)
                Clock.schedule_once(lambda *_dt, msg=msg: _popup("Error", msg), 0)

        Thread(target=work, daemon=True).start()

    def verify_email_otp(self):
        new_email = (self.ids.get("new_email_input").text or "").strip() if self.ids.get("new_email_input") else ""
        otp = (self.ids.get("new_email_otp").text or "").strip() if self.ids.get("new_email_otp") else ""
        if not new_email or not otp:
            _popup("Error", "Enter new email and OTP.")
            return

        from threading import Thread

        def work():
            try:
                data = api_me_change_email_verify(new_email=new_email, otp=otp)
                u = data.get("user") or {}
                sess = get_session() or {}
                set_session(token=str(sess.get("token") or ""), user=u, remember=bool(sess.get("remember_me") or False))
                Clock.schedule_once(lambda *_: self._apply_user(u), 0)
                Clock.schedule_once(lambda *_: _popup("Saved", "Email updated."), 0)
            except ApiError as e:
                msg = str(e)
                Clock.schedule_once(lambda *_dt, msg=msg: _popup("Error", msg), 0)

        Thread(target=work, daemon=True).start()

    def request_phone_otp(self):
        new_phone = (self.ids.get("new_phone_input").text or "").strip() if self.ids.get("new_phone_input") else ""
        if not new_phone:
            _popup("Error", "Enter new phone.")
            return

        from threading import Thread

        def work():
            try:
                data = api_me_change_phone_request_otp(new_phone=new_phone)
                Clock.schedule_once(lambda *_: _popup("OTP", data.get("message") or "OTP sent."), 0)
            except ApiError as e:
                msg = str(e)
                Clock.schedule_once(lambda *_dt, msg=msg: _popup("Error", msg), 0)

        Thread(target=work, daemon=True).start()

    def verify_phone_otp(self):
        new_phone = (self.ids.get("new_phone_input").text or "").strip() if self.ids.get("new_phone_input") else ""
        otp = (self.ids.get("new_phone_otp").text or "").strip() if self.ids.get("new_phone_otp") else ""
        if not new_phone or not otp:
            _popup("Error", "Enter new phone and OTP.")
            return

        from threading import Thread

        def work():
            try:
                data = api_me_change_phone_verify(new_phone=new_phone, otp=otp)
                u = data.get("user") or {}
                sess = get_session() or {}
                set_session(token=str(sess.get("token") or ""), user=u, remember=bool(sess.get("remember_me") or False))
                Clock.schedule_once(lambda *_: self._apply_user(u), 0)
                Clock.schedule_once(lambda *_: _popup("Saved", "Phone updated."), 0)
            except ApiError as e:
                msg = str(e)
                Clock.schedule_once(lambda *_dt, msg=msg: _popup("Error", msg), 0)

        Thread(target=work, daemon=True).start()

    def delete_account(self):
        def do_delete(*_):
            from threading import Thread

            def work():
                try:
                    api_me_delete()
                    clear_session()
                    Clock.schedule_once(lambda *_: _popup("Deleted", "Account deleted."), 0)
                    Clock.schedule_once(lambda *_: setattr(self.manager, "current", "welcome") if self.manager else None, 0)
                except ApiError as e:
                    msg = str(e)
                    Clock.schedule_once(lambda *_dt, msg=msg: _popup("Error", msg), 0)

            Thread(target=work, daemon=True).start()
            popup.dismiss()

        buttons = BoxLayout(size_hint_y=None, height=48, spacing=8, padding=[8, 8])
        btn_yes = HoverButton(text="Delete", background_color=(0.8, 0.2, 0.2, 1))
        btn_no = HoverButton(text="Cancel", background_color=(0.2, 0.5, 0.9, 1))
        buttons.add_widget(btn_no)
        buttons.add_widget(btn_yes)
        root = BoxLayout(orientation="vertical", spacing=8, padding=8)
        root.add_widget(Label(text="Delete your account permanently?\nThis cannot be undone."))
        root.add_widget(buttons)
        popup = Popup(title="Confirm", content=root, size_hint=(0.85, 0.4), auto_dismiss=False)
        btn_no.bind(on_release=lambda *_: popup.dismiss())
        btn_yes.bind(on_release=do_delete)
        popup.open()

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


