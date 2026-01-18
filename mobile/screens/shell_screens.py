from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from kivy.clock import Clock
from kivy.factory import Factory
from kivy.properties import BooleanProperty, DictProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.image import AsyncImage
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen
from kivy.graphics import Color, RoundedRectangle, Line

from frontend_app.utils.api import (
    ApiError,
    api_location_areas,
    api_location_districts,
    api_location_states,
    api_get_property,
    api_get_property_contact,
    api_list_nearby_properties,
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
    api_owner_create_property,
    api_owner_list_properties,
    api_subscription_status,
    api_upload_property_media,
    to_api_url,
)
from frontend_app.utils.storage import clear_session, get_session, get_user, set_guest_session, set_session
from frontend_app.utils.billing import BillingUnavailable, buy_plan
from frontend_app.utils.android_permissions import ensure_permissions, required_location_permissions, required_media_permissions
from frontend_app.utils.android_location import get_last_known_location


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
            is_guest = bool(sess.get("guest"))
            self.manager.current = "home" if (token or is_guest) else "welcome"
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
            is_guest = bool(sess.get("guest"))
            if token or is_guest:
                self.manager.current = "home"
        except Exception:
            return

    def continue_as_guest(self):
        """
        Start a guest session and continue to Home.
        """
        set_guest_session()
        if self.manager:
            self.manager.current = "home"


class HomeScreen(Screen):
    """
    Home / Property Feed + Search & Filters.
    """

    items = ListProperty([])
    need_category = StringProperty("Any")
    need_values = ListProperty(["Any"])

    # Filters matching the web Home page
    state_value = StringProperty("Any")
    district_value = StringProperty("Any")
    area_value = StringProperty("Any")
    radius_km = StringProperty("20")
    gps_status = StringProperty("GPS not available (showing non-nearby results).")
    rent_sale = StringProperty("Any")
    max_price = StringProperty("")
    sort_budget = StringProperty("Any (Newest)")
    posted_within_days = StringProperty("Any")

    state_options = ListProperty(["Any"])
    district_options = ListProperty(["Any"])
    area_options = ListProperty(["Any"])

    bg_image = StringProperty("")

    is_loading = BooleanProperty(False)
    is_logged_in = BooleanProperty(False)
    is_guest = BooleanProperty(False)

    def on_pre_enter(self, *args):
        # Gate buttons until user logs in.
        try:
            sess = get_session() or {}
            token = str(sess.get("token") or "")
            self.is_logged_in = bool(token)
            self.is_guest = bool(sess.get("guest")) and not self.is_logged_in
        except Exception:
            self.is_logged_in = False
            self.is_guest = False

        # Seed preferred location from the stored profile.
        try:
            u = get_user() or {}
            self._preferred_state = str(u.get("state") or "").strip()
            self._preferred_district = str(u.get("district") or "").strip()
        except Exception:
            self._preferred_state = ""
            self._preferred_district = ""

        # Revert to the glossy purple/orange background (no image).
        self.bg_image = ""

        # Load customer "need" categories (non-fatal if offline).
        self._load_need_categories()

        # Load state list (non-fatal if offline).
        self._load_states()

        # Best-effort: refresh user profile for latest location (non-fatal).
        if self.is_logged_in:
            self._refresh_profile_from_server()

        # Best-effort GPS capture (non-fatal); refresh once it becomes available.
        self._ensure_gps_best_effort()

        Clock.schedule_once(lambda _dt: self.refresh(), 0)

    # -----------------------
    # Top nav actions (Home header)
    # -----------------------
    def go_login(self):
        if self.manager:
            self.manager.current = "login"

    def go_register(self):
        if self.manager:
            self.manager.current = "register"

    def go_back_guest(self):
        # Guest "Back" goes to Welcome screen.
        if self.is_logged_in:
            return
        if self.manager:
            self.manager.current = "welcome"

    def go_subscription(self):
        if not self.is_logged_in:
            _popup("Login required", "Please login to open Subscription.")
            if self.manager:
                self.manager.current = "login"
            return
        if self.manager:
            self.manager.current = "subscription"

    def go_my_posts(self):
        if not self.is_logged_in:
            _popup("Login required", "Please login to view My Posts.")
            if self.manager:
                self.manager.current = "login"
            return
        if self.manager:
            self.manager.current = "my_posts"

    def go_settings(self):
        # Settings screen already handles login gating, but keep UX consistent here.
        if not self.is_logged_in:
            _popup("Login required", "Please login to open Settings.")
            if self.manager:
                self.manager.current = "login"
            return
        if self.manager:
            self.manager.current = "profile"

    def go_publish_ad(self):
        self.go_owner()

    def do_logout(self):
        if not self.is_logged_in:
            # Guest "logout" clears guest flag and returns to Welcome.
            try:
                if (get_session() or {}).get("guest"):
                    clear_session()
            except Exception:
                pass
            if self.manager:
                self.manager.current = "welcome"
            return
        clear_session()
        self.is_logged_in = False
        self.is_guest = False
        if self.manager:
            self.manager.current = "welcome"

    def apply_filters(self):
        self.refresh()

    # -----------------------
    # Filter option loaders (State/District/Area)
    # -----------------------
    def _refresh_profile_from_server(self) -> None:
        from threading import Thread

        def work():
            try:
                data = api_me()
                u = data.get("user") or {}
                sess = get_session() or {}
                set_session(token=str(sess.get("token") or ""), user=u, remember=bool(sess.get("remember_me") or False))
                pref_state = str(u.get("state") or "").strip()
                pref_district = str(u.get("district") or "").strip()

                def apply(*_):
                    self._preferred_state = pref_state
                    self._preferred_district = pref_district
                    self._apply_preferred_state()

                Clock.schedule_once(apply, 0)
            except Exception:
                return

        Thread(target=work, daemon=True).start()

    def _apply_preferred_state(self) -> bool:
        pref = str(getattr(self, "_preferred_state", "") or "").strip()
        if not pref:
            return False
        if (self.state_value or "").strip().lower() in {"any", ""} and pref in (self.state_options or []):
            self.state_value = pref
            # Clear after applying once to avoid overriding manual changes.
            self._preferred_state = ""
            return True
        return False

    def _apply_preferred_district(self) -> bool:
        pref = str(getattr(self, "_preferred_district", "") or "").strip()
        if not pref:
            return False
        if (self.district_value or "").strip().lower() in {"any", ""} and pref in (self.district_options or []):
            self.district_value = pref
            self._preferred_district = ""
            return True
        return False

    def _norm_any(self, v: str) -> str:
        v = str(v or "").strip()
        return "" if v.lower() in {"any", ""} else v

    def _load_states(self):
        from threading import Thread

        def work():
            try:
                st = api_location_states().get("items") or []
                st = [str(x).strip() for x in st if str(x).strip()]
                opts = ["Any"] + st

                def apply(*_):
                    self.state_options = opts
                    # Keep selection stable; default to Any.
                    if (self.state_value or "").strip() not in self.state_options:
                        self.state_value = "Any"
                    self._apply_preferred_state()
                    self.on_state_selected()

                Clock.schedule_once(apply, 0)
            except Exception:
                return

        Thread(target=work, daemon=True).start()

    def on_state_selected(self, *_):
        # Reset dependent selections
        self.district_value = "Any"
        self.area_value = "Any"
        self.district_options = ["Any"]
        self.area_options = ["Any"]

        state = self._norm_any(self.state_value)
        if not state:
            return

        from threading import Thread

        def work():
            try:
                ds = api_location_districts(state=state).get("items") or []
                ds = [str(x).strip() for x in ds if str(x).strip()]
                opts = ["Any"] + ds
                def apply(*_):
                    self.district_options = opts
                    if self._apply_preferred_district():
                        self.on_district_selected()

                Clock.schedule_once(apply, 0)
            except Exception:
                return

        Thread(target=work, daemon=True).start()

    def on_district_selected(self, *_):
        self.area_value = "Any"
        self.area_options = ["Any"]
        state = self._norm_any(self.state_value)
        district = self._norm_any(self.district_value)
        if not state or not district:
            return

        from threading import Thread

        def work():
            try:
                ar = api_location_areas(state=state, district=district).get("items") or []
                ar = [str(x).strip() for x in ar if str(x).strip()]
                opts = ["Any"] + ar
                Clock.schedule_once(lambda *_: setattr(self, "area_options", opts), 0)
            except Exception:
                return

        Thread(target=work, daemon=True).start()

    # -----------------------
    # GPS (Nearby)
    # -----------------------
    def _ensure_gps_best_effort(self) -> None:
        def after(ok: bool) -> None:
            loc = get_last_known_location() if ok else None
            if loc:
                self._gps = (float(loc[0]), float(loc[1]))
                self.gps_status = f"Using GPS ({self._gps[0]:.4f}, {self._gps[1]:.4f})"
            else:
                self._gps = None
                self.gps_status = "GPS not available (showing non-nearby results)."

        ensure_permissions(required_location_permissions(), on_result=after)

    def _feed_card(self, raw: dict[str, Any]) -> BoxLayout:
        """
        Build a feed card roughly matching the web UI:
        title/meta header, optional media preview, and an action button.
        """
        p = raw or {}
        title = str(p.get("title") or "Property").strip()
        adv_no = str(p.get("adv_number") or p.get("ad_number") or p.get("id") or "").strip()
        meta = " • ".join(
            [x for x in [f"Ad #{adv_no}" if adv_no else "", str(p.get("rent_sale") or ""), str(p.get("property_type") or ""), str(p.get("price_display") or ""), str(p.get("location_display") or "")] if x]
        )
        images = p.get("images") or []

        card = BoxLayout(orientation="vertical", padding=(12, 10), spacing=8, size_hint_y=None)
        card.bind(minimum_height=card.setter("height"))

        # Card background
        with card.canvas.before:
            Color(0, 0, 0, 0.35)
            rect = RoundedRectangle(pos=card.pos, size=card.size, radius=[16])
            Color(1, 1, 1, 0.12)
            border = Line(rounded_rectangle=[card.x, card.y, card.width, card.height, 16], width=1.0)

        def _sync_bg(*_):
            rect.pos = card.pos
            rect.size = card.size
            border.rounded_rectangle = [card.x, card.y, card.width, card.height, 16]

        card.bind(pos=_sync_bg, size=_sync_bg)

        header = BoxLayout(orientation="horizontal", spacing=10, size_hint_y=None, height=48)
        avatar = Label(text=(title[:1].upper() if title else "A"), size_hint=(None, None), size=(42, 42), halign="center", valign="middle")
        avatar.text_size = avatar.size
        header.add_widget(avatar)

        hb = BoxLayout(orientation="vertical", spacing=2)
        hb.add_widget(Label(text=f"[b]{title}[/b]", size_hint_y=None, height=24))
        hb.add_widget(Label(text=str(meta), size_hint_y=None, height=20, color=(1, 1, 1, 0.85)))
        header.add_widget(hb)
        card.add_widget(header)

        if images:
            first = images[0] or {}
            ctype = str(first.get("content_type") or "").lower()
            if ctype.startswith("image/"):
                img = AsyncImage(source=to_api_url(first.get("url") or ""), allow_stretch=True)
                img.size_hint_y = None
                img.height = 200
                card.add_widget(img)
            else:
                card.add_widget(Label(text="(Video attached)", size_hint_y=None, height=20, color=(1, 1, 1, 0.85)))
        else:
            card.add_widget(Label(text="Photos will appear once uploaded.", size_hint_y=None, height=20, color=(1, 1, 1, 0.85)))

        btn_row = BoxLayout(orientation="horizontal", spacing=10, size_hint_y=None, height=44)
        btn_open = Factory.AppButton(text="Open", size_hint_y=None, height=44)
        btn_open.bind(on_release=lambda *_: self.open_post_popup(p))
        btn_row.add_widget(btn_open)
        card.add_widget(btn_row)

        return card

    def _load_need_categories(self):
        def work():
            try:
                data = api_meta_categories()
                cats = data.get("categories") or []
                values: list[str] = ["Any"]
                if cats:
                    for g in cats:
                        items = (g or {}).get("items") or []
                        for it in items:
                            label = str(it or "").strip()
                            if label:
                                values.append(label)
                else:
                    # Fallback to flat items if categories array is missing.
                    flat = data.get("flat_items") or []
                    for it in flat:
                        label = str((it or {}).get("label") or "").strip()
                        if label:
                            values.append(label)

                # De-dup while keeping order
                seen: set[str] = set()
                deduped = []
                for v in values:
                    if v in seen:
                        continue
                    seen.add(v)
                    deduped.append(v)

                def apply(*_):
                    setattr(self, "need_values", deduped)
                    warning = str(data.get("warning") or "").strip()
                    if warning and not getattr(self, "_warned_categories", False):
                        self._warned_categories = True
                        _popup("Categories", warning)
                    if len(deduped) <= 1 and not getattr(self, "_warned_categories", False):
                        self._warned_categories = True
                        _popup("Categories", "Category list is unavailable. Showing default options.")

                Clock.schedule_once(apply, 0)
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
                q = need if need and need.lower() != "any" else ""
                rent_sale = self._norm_any(self.rent_sale)
                max_price = (self.max_price or "").strip()
                state = self._norm_any(self.state_value)
                district = self._norm_any(self.district_value)
                area = self._norm_any(self.area_value)

                sort_budget = (self.sort_budget or "").strip()
                sort_budget_param = ""
                if sort_budget.lower().startswith("top"):
                    sort_budget_param = "top"
                elif sort_budget.lower().startswith("bottom"):
                    sort_budget_param = "bottom"

                posted = (self.posted_within_days or "").strip()
                posted_param = ""
                if posted.lower() == "today":
                    posted_param = "1"
                elif posted.lower().startswith("last 7"):
                    posted_param = "7"
                elif posted.lower().startswith("last 30"):
                    posted_param = "30"
                elif posted.lower().startswith("last 90"):
                    posted_param = "90"

                # Nearby endpoint if GPS is available; otherwise fall back to non-GPS listing.
                loc = getattr(self, "_gps", None)
                try:
                    radius = int(str(self.radius_km or "").strip() or "20")
                except Exception:
                    radius = 20

                if loc:
                    data = api_list_nearby_properties(
                        lat=float(loc[0]),
                        lon=float(loc[1]),
                        radius_km=radius,
                        q=q,
                        rent_sale=rent_sale,
                        max_price=max_price,
                        state=state,
                        district=district,
                        area=area,
                        posted_within_days=posted_param,
                        limit=60,
                    )
                else:
                    data = api_list_properties(
                        q=q,
                        rent_sale=rent_sale,
                        max_price=max_price,
                        state=state,
                        district=district,
                        area=area,
                        sort_budget=sort_budget_param,
                        posted_within_days=posted_param,
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
                            "raw": p,
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
                                raw = c.get("raw") or {}
                                container.add_widget(self._feed_card(raw))
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

    def open_post_popup(self, p: dict[str, Any]):
        """
        Show the post details inline (no redirect screen).
        Includes Photos, Amenities, and Contact owner.
        """
        pid = int(p.get("id") or 0)
        title = str(p.get("title") or "Post")
        meta = " • ".join([x for x in [str(p.get("rent_sale") or ""), str(p.get("property_type") or ""), str(p.get("price_display") or ""), str(p.get("location_display") or "")] if x])
        amenities = p.get("amenities") or []
        images = p.get("images") or []

        root = BoxLayout(orientation="vertical", spacing=8, padding=10)
        root.add_widget(Label(text=f"[b]{title}[/b]", size_hint_y=None, height=34))
        root.add_widget(Label(text=str(meta), size_hint_y=None, height=22, color=(1, 1, 1, 0.85)))

        root.add_widget(Label(text="[b]Photos[/b]", size_hint_y=None, height=22))
        if images:
            first = images[0] or {}
            ctype = str(first.get("content_type") or "").lower()
            if ctype.startswith("image/"):
                img = AsyncImage(source=to_api_url(first.get("url") or ""), allow_stretch=True)
                img.size_hint_y = None
                img.height = 220
                root.add_widget(img)
            else:
                root.add_widget(Label(text="(Video attached)", size_hint_y=None, height=22, color=(1, 1, 1, 0.85)))
        else:
            root.add_widget(Label(text="Photos will appear once uploaded.", size_hint_y=None, height=22, color=(1, 1, 1, 0.85)))

        root.add_widget(Label(text="[b]Amenities[/b]", size_hint_y=None, height=22))
        root.add_widget(Label(text=(", ".join([str(x) for x in amenities]) if amenities else "—"), size_hint_y=None, height=44, color=(1, 1, 1, 0.85)))

        btn_contact = Factory.AppButton(text="Contact owner", size_hint_y=None, height=46)
        root.add_widget(btn_contact)
        lbl_status = Label(text="", size_hint_y=None, height=40, color=(1, 1, 1, 0.85))
        root.add_widget(lbl_status)

        popup = Popup(title="Post", content=root, size_hint=(0.92, 0.90), auto_dismiss=True)

        def do_contact(*_):
            sess = get_session() or {}
            if not (sess.get("token") or ""):
                _popup("Login required", "Please login to view contact details.")
                if self.manager:
                    self.manager.current = "login"
                popup.dismiss()
                return

            btn_contact.disabled = True

            def work():
                try:
                    contact = api_get_property_contact(pid)
                    owner_name = str(contact.get("owner_name") or "").strip()
                    adv_no = str(contact.get("adv_number") or contact.get("advNo") or pid).strip()

                    def done(*_dt):
                        btn_contact.text = "Contacted"
                        who = f" ({owner_name})" if owner_name else ""
                        lbl_status.text = f"Contact details sent to your registered email/SMS for Ad #{adv_no}{who}."

                    Clock.schedule_once(done, 0)
                except ApiError as e:
                    msg = str(e)

                    def fail(*_dt):
                        btn_contact.disabled = False
                        lbl_status.text = msg
                        # If locked, guide to subscription screen (no special quota messaging).
                        if "subscription" in msg.lower() and self.manager:
                            self.manager.current = "subscription"

                    Clock.schedule_once(fail, 0)

            from threading import Thread

            Thread(target=work, daemon=True).start()

        btn_contact.bind(on_release=do_contact)
        popup.open()

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
        - Call the backend unlock endpoint (it enforces free quota / subscription).
        - Show a confirmation that details were sent via Email/SMS.
        """
        sess = get_session() or {}
        if not (sess.get("token") or ""):
            _popup("Login required", "Please login to view contact details.")
            if self.manager:
                self.manager.current = "login"
            return

        def work():
            try:
                contact = api_get_property_contact(self.property_id)
                owner_name = str(contact.get("owner_name") or "").strip()
                adv_no = str(contact.get("adv_number") or contact.get("advNo") or self.property_id).strip()
                who = f" ({owner_name})" if owner_name else ""
                Clock.schedule_once(lambda *_: _popup("Success", f"Contact details sent to your registered email/SMS for Ad #{adv_no}{who}."), 0)
            except ApiError as e:
                msg = str(e)
                def fail(*_dt):
                    _popup("Error", msg)
                    if "subscription required" in msg.lower() and self.manager:
                        self.manager.current = "subscription"

                Clock.schedule_once(fail, 0)

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

    def simulate_google_play_success(self, product_id: str = ""):
        pid = str(product_id or "").strip()
        if not pid:
            _popup("Billing", "Missing product id.")
            return
        try:
            buy_plan(pid)
            _popup("Billing", f"Launching Google Play purchase for:\n{pid}")
        except BillingUnavailable:
            # Desktop/dev fallback.
            _popup("Google Play Billing (demo)", f"Product: {pid}\n\nAndroid billing bridge not available in this build.")

    def back(self):
        if self.manager:
            self.manager.current = "property_detail"


class MyPostsScreen(Screen):
    """
    Owner/User posts list (server-backed).
    """

    is_loading = BooleanProperty(False)

    def on_pre_enter(self, *args):
        self.refresh()

    def refresh(self):
        if self.is_loading:
            return
        self.is_loading = True

        from threading import Thread

        def work():
            try:
                data = api_owner_list_properties()
                items = data.get("items") or []

                def done(*_):
                    try:
                        container = self.ids.get("my_posts_container")
                        if container is not None:
                            container.clear_widgets()
                            if not items:
                                container.add_widget(
                                    Label(text="No posts yet.", size_hint_y=None, height=32, color=(1, 1, 1, 0.75))
                                )
                            else:
                                # Reuse HomeScreen card layout when possible.
                                home = self.manager.get_screen("home") if self.manager else None
                                for p in items:
                                    if home and hasattr(home, "_feed_card"):
                                        container.add_widget(home._feed_card(p))  # type: ignore[attr-defined]
                                    else:
                                        title = str((p or {}).get("title") or "Post")
                                        container.add_widget(Label(text=title, size_hint_y=None, height=32))
                    except Exception:
                        pass
                    self.is_loading = False

                Clock.schedule_once(done, 0)
            except ApiError as e:
                msg = str(e)
                Clock.schedule_once(lambda *_dt, msg=msg: _popup("Error", msg), 0)
                Clock.schedule_once(lambda *_: setattr(self, "is_loading", False), 0)
            except Exception as e:
                msg = str(e) or "Failed to load posts."
                Clock.schedule_once(lambda *_dt, msg=msg: _popup("Error", msg), 0)
                Clock.schedule_once(lambda *_: setattr(self, "is_loading", False), 0)

        Thread(target=work, daemon=True).start()

    def back(self):
        if self.manager:
            self.manager.current = "home"


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
        def _open_picker() -> None:
            chooser = FileChooserListView(path=os.path.expanduser("~"), filters=["*.png", "*.jpg", "*.jpeg", "*.webp"])

            # Auto-upload on selection (no separate Save/Upload button).
            popup = Popup(title="Choose Profile Image", size_hint=(0.9, 0.9), auto_dismiss=False)

            def on_selection(*_args):
                try:
                    if not chooser.selection:
                        return
                    fp = chooser.selection[0]
                    popup.dismiss()
                    self.upload_profile_image(fp)
                except Exception:
                    # Never crash UI due to picker errors.
                    popup.dismiss()

            try:
                chooser.bind(selection=lambda *_: on_selection())
            except Exception:
                pass

            buttons = BoxLayout(size_hint_y=None, height=48, spacing=8, padding=[8, 8])
            btn_cancel = Factory.AppButton(text="Cancel", color=(0.94, 0.27, 0.27, 1))
            buttons.add_widget(btn_cancel)

            root = BoxLayout(orientation="vertical", spacing=8, padding=8)
            root.add_widget(Label(text="Tap an image to upload immediately."))
            root.add_widget(chooser)
            root.add_widget(buttons)

            popup.content = root
            btn_cancel.bind(on_release=lambda *_: popup.dismiss())
            popup.open()

        def _after(ok: bool) -> None:
            if not ok:
                _popup("Permission required", "Please allow Photos/Media permission to upload images.")
                return
            _open_picker()

        ensure_permissions(required_media_permissions(), on_result=_after)

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
        btn_yes = Factory.AppButton(text="Delete", color=(0.94, 0.27, 0.27, 1))
        btn_no = Factory.AppButton(text="Cancel")
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
    def on_pre_enter(self, *args):
        # Load location dropdowns from backend (and default to profile state/district if present).
        u = get_user() or {}
        preferred_state = str(u.get("state") or "").strip()
        preferred_district = str(u.get("district") or "").strip()

        from threading import Thread

        def work():
            try:
                st = api_location_states().get("items") or []
                st = [str(x).strip() for x in st if str(x).strip()]

                def apply_states(*_):
                    self._states_cache = st
                    if "state_spinner" in self.ids:
                        sp = self.ids["state_spinner"]
                        sp.values = self.state_values()
                        if preferred_state and preferred_state in sp.values:
                            sp.text = preferred_state
                        elif (sp.text or "").strip() in {"Select State", ""}:
                            sp.text = "Tamil Nadu" if "Tamil Nadu" in sp.values else (sp.values[0] if sp.values else "Select State")
                    self.on_state_changed()
                    # Try to set preferred district after districts load (best-effort).
                    if preferred_district:
                        Clock.schedule_once(lambda *_: self._apply_preferred_district(preferred_district), 0.2)

                Clock.schedule_once(apply_states, 0)
            except Exception:
                Clock.schedule_once(lambda *_: setattr(self, "_states_cache", []), 0)

        Thread(target=work, daemon=True).start()

    def _apply_preferred_district(self, preferred_district: str):
        try:
            if "district_spinner" not in self.ids:
                return
            sp = self.ids["district_spinner"]
            if preferred_district and preferred_district in (sp.values or []):
                sp.text = preferred_district
                self.on_district_changed()
        except Exception:
            return

    def state_values(self):
        return list(getattr(self, "_states_cache", []) or [])

    def district_values(self):
        return list(getattr(self, "_districts_cache", []) or [])

    def area_values(self):
        return list(getattr(self, "_areas_cache", []) or [])

    def on_state_changed(self, *_):
        if "district_spinner" not in self.ids:
            return
        state = (self.ids.get("state_spinner").text or "").strip() if self.ids.get("state_spinner") else ""
        # Reset dependent spinners
        try:
            self.ids["district_spinner"].text = "Select District"
        except Exception:
            pass
        try:
            if "area_spinner" in self.ids:
                self.ids["area_spinner"].text = "Select Area"
                self.ids["area_spinner"].values = []
        except Exception:
            pass

        if not state or state in {"Select State", "Select Country"}:
            self._districts_cache = []
            try:
                self.ids["district_spinner"].values = []
            except Exception:
                pass
            return

        from threading import Thread

        def work():
            try:
                ds = api_location_districts(state=state).get("items") or []
                ds = [str(x).strip() for x in ds if str(x).strip()]

                def apply(*_dt):
                    self._districts_cache = ds
                    try:
                        self.ids["district_spinner"].values = self.district_values()
                    except Exception:
                        pass

                Clock.schedule_once(apply, 0)
            except Exception:
                Clock.schedule_once(lambda *_: setattr(self, "_districts_cache", []), 0)

        Thread(target=work, daemon=True).start()

    def on_district_changed(self, *_):
        if "area_spinner" not in self.ids:
            return
        state = (self.ids.get("state_spinner").text or "").strip() if self.ids.get("state_spinner") else ""
        district = (self.ids.get("district_spinner").text or "").strip() if self.ids.get("district_spinner") else ""
        try:
            self.ids["area_spinner"].text = "Select Area"
        except Exception:
            pass
        if not state or not district or district in {"Select District"}:
            self._areas_cache = []
            try:
                self.ids["area_spinner"].values = []
            except Exception:
                pass
            return

        from threading import Thread

        def work():
            try:
                ar = api_location_areas(state=state, district=district).get("items") or []
                ar = [str(x).strip() for x in ar if str(x).strip()]

                def apply(*_dt):
                    self._areas_cache = ar
                    try:
                        self.ids["area_spinner"].values = self.area_values()
                    except Exception:
                        pass

                Clock.schedule_once(apply, 0)
            except Exception:
                Clock.schedule_once(lambda *_: setattr(self, "_areas_cache", []), 0)

        Thread(target=work, daemon=True).start()

    def open_media_picker(self):
        """
        Pick up to 10 images + 1 video to upload with the ad.
        """
        def _open_picker() -> None:
            chooser = FileChooserListView(
                path=os.path.expanduser("~"),
                filters=["*.png", "*.jpg", "*.jpeg", "*.webp", "*.gif", "*.mp4", "*.mov", "*.m4v", "*.avi", "*.mkv"],
                multiselect=True,
            )
            popup = Popup(title="Choose Media (max 10 images + 1 video)", size_hint=(0.92, 0.92), auto_dismiss=False)

            def _is_image(fp: str) -> bool:
                ext = os.path.splitext(fp.lower())[1]
                return ext in {".png", ".jpg", ".jpeg", ".webp", ".gif"}

            def _is_video(fp: str) -> bool:
                ext = os.path.splitext(fp.lower())[1]
                return ext in {".mp4", ".mov", ".m4v", ".avi", ".mkv"}

            def apply_selection(*_):
                try:
                    selected = list(chooser.selection or [])
                    images = [x for x in selected if _is_image(x)]
                    videos = [x for x in selected if _is_video(x)]
                    others = [x for x in selected if (not _is_image(x)) and (not _is_video(x))]
                    if others:
                        _popup("Error", "Only image/video files are allowed.")
                        return
                    if len(images) > 10:
                        _popup("Error", "Maximum 10 images are allowed.")
                        return
                    if len(videos) > 1:
                        _popup("Error", "Maximum 1 video is allowed.")
                        return
                    self._selected_media = images + videos
                    try:
                        if "media_summary" in self.ids:
                            parts: list[str] = []
                            if images:
                                parts.append(f"{len(images)} image(s)")
                            if videos:
                                parts.append("1 video")
                            self.ids["media_summary"].text = ("Selected: " + " + ".join(parts)) if parts else ""
                    except Exception:
                        pass
                    popup.dismiss()
                except Exception:
                    popup.dismiss()

            buttons = BoxLayout(size_hint_y=None, height=48, spacing=8, padding=[8, 8])
            btn_cancel = Factory.AppButton(text="Cancel", color=(0.94, 0.27, 0.27, 1))
            btn_ok = Factory.AppButton(text="Use Selected")
            buttons.add_widget(btn_cancel)
            buttons.add_widget(btn_ok)

            root = BoxLayout(orientation="vertical", spacing=8, padding=8)
            root.add_widget(Label(text="Select up to 10 images and optionally 1 video."))
            root.add_widget(chooser)
            root.add_widget(buttons)
            popup.content = root
            btn_cancel.bind(on_release=lambda *_: popup.dismiss())
            btn_ok.bind(on_release=apply_selection)
            popup.open()

        def _after(ok: bool) -> None:
            if not ok:
                _popup("Permission required", "Please allow Photos/Media permission to pick files for upload.")
                return
            _open_picker()

        ensure_permissions(required_media_permissions(), on_result=_after)

    def submit_listing(self):
        """
        Create the ad (goes to admin review).
        Location/Address are removed from UI as requested.
        """
        title = (self.ids.get("title_input").text or "").strip() if self.ids.get("title_input") else ""
        state = (self.ids.get("state_spinner").text or "").strip() if self.ids.get("state_spinner") else ""
        district = (self.ids.get("district_spinner").text or "").strip() if self.ids.get("district_spinner") else ""
        area = (self.ids.get("area_spinner").text or "").strip() if self.ids.get("area_spinner") else ""
        category = (self.ids.get("category_spinner").text or "").strip().lower() if self.ids.get("category_spinner") else "property"
        price_text = (self.ids.get("price_input").text or "").strip() if self.ids.get("price_input") else ""
        rent_sale = (self.ids.get("rent_sale_spinner").text or "").strip().lower() if self.ids.get("rent_sale_spinner") else "rent"
        contact_phone = (self.ids.get("contact_phone_input").text or "").strip() if self.ids.get("contact_phone_input") else ""

        if not state or state in {"Select State", "Select Country"}:
            _popup("Error", "Please select state.")
            return
        if not district or district in {"Select District"}:
            _popup("Error", "Please select district.")
            return
        if not area or area in {"Select Area"}:
            _popup("Error", "Please select area.")
            return
        if not title:
            _popup("Error", "Please enter title.")
            return
        if category not in {"materials", "services", "property"}:
            _popup("Error", "Please select category.")
            return

        try:
            price = int(price_text) if price_text else 0
        except Exception:
            _popup("Error", "Enter a valid price.")
            return

        from threading import Thread
        # api_owner_create_property imported at module level

        def _start_submit(gps_lat: float | None, gps_lng: float | None) -> None:
            try:
                payload = {
                    "state": state,
                    "district": district,
                    "area": area,
                    "title": title,
                    # Use district as a simple display location.
                    "location": area or district,
                    "address": "",
                    "price": price,
                    "rent_sale": rent_sale if rent_sale in {"rent", "sale"} else "rent",
                    "property_type": category,
                    "contact_phone": contact_phone,
                    "contact_email": "",
                    "amenities": [],
                    # GPS is optional; omit by sending nulls.
                    "gps_lat": gps_lat,
                    "gps_lng": gps_lng,
                }
                res = api_owner_create_property(payload=payload)
                pid = res.get("id")
                status = res.get("status") or "pending"

                # Upload selected media (best-effort).
                selected = list(getattr(self, "_selected_media", []) or [])
                if pid and selected:
                    for i, fp in enumerate(selected):
                        api_upload_property_media(property_id=int(pid), file_path=str(fp), sort_order=i)

                def done(*_):
                    msg = f"Ad created (#{pid}) • status: {status}"
                    if selected:
                        msg += f"\nUploaded {len(selected)} file(s)."
                    _popup("Submitted", msg)
                    if self.manager:
                        self.manager.current = "owner_dashboard"

                Clock.schedule_once(done, 0)
            except ApiError as e:
                msg = str(e)
                Clock.schedule_once(lambda *_dt, msg=msg: _popup("Error", msg), 0)

        def _maybe_with_location(ok: bool) -> None:
            loc = get_last_known_location() if ok else None
            gps_lat, gps_lng = (loc[0], loc[1]) if loc else (None, None)

            def work():
                _start_submit(gps_lat, gps_lng)

            Thread(target=work, daemon=True).start()

        # Request location permission at runtime (best-effort). Submission continues even if denied.
        ensure_permissions(required_location_permissions(), on_result=_maybe_with_location)

    def go_back(self):
        if self.manager:
            self.manager.current = "owner_dashboard"


