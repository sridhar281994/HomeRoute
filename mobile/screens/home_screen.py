from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from kivy.clock import Clock
from kivy.factory import Factory
from kivy.metrics import dp, sp
from kivy.properties import (
    BooleanProperty,
    ListProperty,
    ObjectProperty,
    StringProperty,
)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.checkbox import CheckBox
from kivy.uix.carousel import Carousel
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import AsyncImage
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.screenmanager import Screen
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.graphics import Color, Line, RoundedRectangle

from frontend_app.utils.android_location import get_last_known_location, open_location_settings
from frontend_app.utils.android_permissions import ensure_permissions, required_location_permissions
from frontend_app.utils.api import (
    ApiError,
    api_get_property_contact,
    api_list_nearby_properties,
    api_list_properties,
    api_location_areas,
    api_location_districts,
    api_location_states,
    api_me,
    api_meta_categories,
    to_api_url,
)


# Media sizing for post images.
# - Upscale tiny/wide panoramas so they are still readable.
# - Cap very tall images so a single post doesn't dominate the feed.
_POST_MEDIA_MIN_H = dp(240)
_POST_MEDIA_MAX_H = dp(520)
from frontend_app.utils.share import share_text
from frontend_app.utils.storage import clear_session, get_session, get_user, set_guest_session, set_session

from screens.gestures import GestureNavigationMixin


def _popup(title: str, message: str) -> None:
    def _open(*_):
        popup = Popup(
            title=title,
            content=Label(text=str(message)),
            size_hint=(0.78, 0.35),
            auto_dismiss=True,
        )
        popup.open()
        Clock.schedule_once(lambda _dt: popup.dismiss(), 2.2)

    Clock.schedule_once(_open, 0)


def _is_payment_required_msg(msg: str) -> bool:
    m = (msg or "").strip().lower()
    return (
        "subscription required" in m
        or "payment required" in m
        or "unlock limit reached" in m
        or "http 402" in m
        or "http 429" in m
    )


def _payment_required_popup(*, screen: "HomeScreen", detail: str = "") -> None:
    """
    Friendly paywall popup for contact unlocks.
    """

    def _open(*_):
        root = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(12))
        msg = "[b]Payment required[/b]\nSubscribe to unlock more owner/service contacts."
        lbl = Label(text=msg, markup=True, halign="center", valign="middle")
        lbl.text_size = (dp(280), None)
        lbl.size_hint_y = None
        lbl.height = lbl.texture_size[1] + dp(10)
        root.add_widget(lbl)

        if (detail or "").strip():
            d = Label(text=str(detail).strip(), color=(1, 1, 1, 0.72), halign="center", valign="middle")
            d.text_size = (dp(280), None)
            d.size_hint_y = None
            d.height = d.texture_size[1] + dp(6)
            root.add_widget(d)

        btns = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
        btn_cancel = Factory.AppButton(text="Not now", color=(0.94, 0.27, 0.27, 1))
        btn_sub = Factory.AppButton(text="View subscription")
        btns.add_widget(btn_cancel)
        btns.add_widget(btn_sub)
        root.add_widget(btns)

        popup = Popup(title="", content=root, size_hint=(0.9, 0.42), auto_dismiss=False)

        def go_sub(*_):
            try:
                popup.dismiss()
            except Exception:
                pass
            try:
                if screen.manager:
                    screen.manager.current = "subscription"
            except Exception:
                pass

        btn_cancel.bind(on_release=lambda *_: popup.dismiss())
        btn_sub.bind(on_release=go_sub)
        popup.open()

    Clock.schedule_once(_open, 0)

@dataclass
class PropertyCard:
    id: int
    title: str
    price: str
    location: str
    kind: str
    rent_sale: str


class FilterPopup(Popup):
    """
    Popup to edit Home screen filters.

    The KV rule binds UI directly to the `home` screen instance.
    """

    home = ObjectProperty(None)

    def on_open(self):
        try:
            if self.home is not None:
                setattr(self.home, "_filter_popup", self)
                container = self.ids.get("area_options_container")
                if container is not None:
                    self.home.render_area_options(container)
        except Exception:
            return

    def on_dismiss(self):
        try:
            if self.home is not None and getattr(self.home, "_filter_popup", None) is self:
                setattr(self.home, "_filter_popup", None)
        except Exception:
            pass
        return super().on_dismiss()


class AreaSelectPopup(Popup):
    """
    Multi-select picker for Areas with search + checkboxes.
    """

    home = ObjectProperty(None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.title = "Select Areas"
        self.size_hint = (0.95, 0.9)
        self.auto_dismiss = True
        self._query = ""
        self._selected: set[str] = set()
        try:
            if self.home is not None:
                self._selected = set([str(x).strip() for x in (self.home.selected_areas or []) if str(x).strip()])
        except Exception:
            self._selected = set()
        self._build()

    def _areas_all(self) -> list[str]:
        try:
            opts = list(getattr(self.home, "area_options", []) or [])
        except Exception:
            opts = []
        opts = [str(x).strip() for x in opts if str(x).strip() and str(x).strip().lower() != "any"]
        return opts

    def _areas_filtered(self) -> list[str]:
        q = str(getattr(self, "_query", "") or "").strip().lower()
        items = self._areas_all()
        if not q:
            return items
        return [x for x in items if q in x.lower()]

    def _build(self) -> None:
        root = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))

        search = TextInput(hint_text="Search areas…", multiline=False, size_hint_y=None, height=dp(44))

        list_wrap = ScrollView(do_scroll_x=False)
        grid = GridLayout(cols=1, spacing=dp(6), size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        list_wrap.add_widget(grid)

        def rebuild(*_):
            grid.clear_widgets()
            for a in self._areas_filtered():
                row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(42), spacing=dp(10))
                cb = CheckBox(active=(a in self._selected), size_hint=(None, None), size=(dp(32), dp(32)))
                lbl = Label(text=a, halign="left", valign="middle", color=(1, 1, 1, 0.92))
                # Do not force `text_size` to 0-width; it truncates to the first letter.
                lbl.size_hint_x = 1

                def _toggle(_cb, value, a=a):
                    if bool(value):
                        self._selected.add(a)
                    else:
                        self._selected.discard(a)

                cb.bind(active=_toggle)
                row.add_widget(cb)
                row.add_widget(lbl)
                grid.add_widget(row)

            if not self._areas_all():
                grid.add_widget(
                    Label(text="No areas available.", size_hint_y=None, height=dp(32), color=(1, 1, 1, 0.75)))

        def on_search(*_):
            self._query = (search.text or "").strip()
            rebuild()

        search.bind(text=lambda *_: on_search())

        btns = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
        btn_clear = Factory.AppButton(text="Clear")
        btn_apply = Factory.AppButton(text="Apply")
        btns.add_widget(btn_clear)
        btns.add_widget(btn_apply)

        def do_clear(*_):
            self._selected = set()
            rebuild()

        def do_apply(*_):
            try:
                if self.home is not None:
                    self.home.selected_areas = sorted(self._selected)
            except Exception:
                pass
            self.dismiss()

        btn_clear.bind(on_release=do_clear)
        btn_apply.bind(on_release=do_apply)

        root.add_widget(search)
        root.add_widget(list_wrap)
        root.add_widget(btns)
        self.content = root
        rebuild()


class HomeScreen(GestureNavigationMixin, Screen):
    """
    Home / Property Feed + Search & Filters.
    """

    items = ListProperty([])
    need_category = StringProperty("Any")
    need_values = ListProperty(["Any"])

    # Filters matching the web Home page
    post_group = StringProperty("property_material")  # property_material | services
    state_value = StringProperty("Any")
    district_value = StringProperty("Any")
    area_value = StringProperty("Any")
    selected_areas = ListProperty([])
    area_search = StringProperty("")
    # Kept for backward compatibility, but radius is no longer shown in Filters UI.
    radius_km = StringProperty("200")
    gps_status = StringProperty("GPS not available (showing non-nearby results).")
    gps_msg = StringProperty("")
    nearby_mode = BooleanProperty(False)
    rent_sale = StringProperty("Any")
    max_price = StringProperty("")
    sort_budget = StringProperty("Any (Newest)")
    posted_within_days = StringProperty("Any")
    need_search = StringProperty("")
    need_values_filtered = ListProperty(["Any"])
    error_msg = StringProperty("")

    state_options = ListProperty(["Any"])
    district_options = ListProperty(["Any"])
    area_options = ListProperty(["Any"])

    bg_image = StringProperty("")
    profile_image_url = StringProperty("")
    avatar_letter = StringProperty("U")

    is_loading = BooleanProperty(False)
    is_logged_in = BooleanProperty(False)
    is_guest = BooleanProperty(False)

    def on_pre_enter(self, *args):
        try:
            sess = get_session() or {}
            token = str(sess.get("token") or "")
            self.is_logged_in = bool(token)
            self.is_guest = bool(sess.get("guest")) and not self.is_logged_in
        except Exception:
            self.is_logged_in = False
            self.is_guest = False

        # ✅ DELAY avatar application (CRITICAL FIX)
        Clock.schedule_once(lambda dt: self._apply_avatar(get_user() or {}), 0)

        # Do not auto-apply profile location into feed filters.
        # Filters must remain stable unless user changes them explicitly.
        self._preferred_state = ""
        self._preferred_district = ""
        self.bg_image = ""

        self._load_need_categories()
        self._load_states()

        Clock.schedule_once(lambda dt: self._render_area_options(), 0)
        Clock.schedule_once(lambda dt: self._render_area_chips(), 0)

        if self.is_logged_in:
            self._refresh_profile_from_server()

        self._ensure_gps_best_effort()

        Clock.schedule_once(lambda dt: self.refresh(), 0)

        self.gesture_bind_window()

    def on_leave(self, *args):
        # Avoid leaking Window bindings when screen is not visible.
        try:
            self.gesture_unbind_window()
        except Exception:
            pass
        return super().on_leave(*args)

    # -----------------------
    # Gesture handlers (pull-to-refresh)
    # -----------------------
    def gesture_can_refresh(self) -> bool:
        """
        Only allow pull-to-refresh when:
        - not already loading
        - feed scroll is at the top
        """
        if self.is_loading:
            return False
        sv = None
        try:
            sv = (self.ids or {}).get("feed_scroll")
        except Exception:
            sv = None
        if sv is None:
            return False
        try:
            # In Kivy ScrollView, scroll_y==1 means top.
            return float(getattr(sv, "scroll_y", 0.0) or 0.0) >= 0.99
        except Exception:
            return False

    def gesture_refresh(self) -> None:
        # Reuse existing refresh logic (same as tapping "Refresh").
        try:
            self.refresh()
        except Exception:
            return

    # -----------------------
    # Top nav actions (Home header)
    # -----------------------
    def go_home(self):
        if self.manager and self.manager.current != "home":
            self.manager.current = "home"
        self.refresh()

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

    def go_back(self):
        """
        Swipe-back handler.
        Home is the root screen for logged-in users; for guests we go back to Welcome.
        """
        if not self.manager:
            return
        if self.is_logged_in:
            return
        self.manager.current = "welcome"

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

    def go_subscription(self):
        if not self.is_logged_in:
            _popup("Login required", "Please login to view Subscription.")
            if self.manager:
                self.manager.current = "login"
            return
        if self.manager:
            self.manager.current = "subscription"

    def go_publish_ad(self):
        # Publish Ad should go straight to the Publish Ad page (no dashboard).
        self.go_owner()

    def do_logout(self):
        if not self.is_logged_in:
            # Guest "logout" clears guest flag and returns to Welcome.
            try:
                if (get_session() or {}).get("guest"):
                    clear_session()
            except Exception:
                pass
            try:
                from kivy.app import App as _App

                a = _App.get_running_app()
                if a and hasattr(a, "sync_user_badge"):
                    a.sync_user_badge()  # type: ignore[attr-defined]
            except Exception:
                pass
            if self.manager:
                self.manager.current = "welcome"
            return
        clear_session()
        try:
            from kivy.app import App as _App

            a = _App.get_running_app()
            if a and hasattr(a, "sync_user_badge"):
                a.sync_user_badge()  # type: ignore[attr-defined]
        except Exception:
            pass
        self.is_logged_in = False
        self.is_guest = False
        if self.manager:
            self.manager.current = "welcome"

    def open_filters(self):
        FilterPopup(home=self).open()

    def open_area_picker(self):
        AreaSelectPopup(home=self).open()

    def clear_areas(self) -> None:
        self.selected_areas = []
        self.area_search = ""
        self._schedule_area_render()
        self._schedule_area_chips()

    def remove_area(self, area: str) -> None:
        area = str(area or "").strip()
        if not area:
            return
        current = [str(x).strip() for x in (self.selected_areas or []) if str(x).strip()]
        if area not in current:
            return
        current = [x for x in current if x != area]
        self.selected_areas = current
        self._schedule_area_render()
        self._schedule_area_chips()

    def toggle_area(self, area: str, enabled: bool) -> None:
        area = str(area or "").strip()
        if not area:
            return
        current = [str(x).strip() for x in (self.selected_areas or []) if str(x).strip()]
        if enabled:
            if area not in current:
                current.append(area)
        else:
            current = [x for x in current if x != area]
        self.selected_areas = current
        self._schedule_area_chips()

    def on_area_search(self, *_):
        self._schedule_area_render()

    def on_area_options(self, *_):
        self._schedule_area_render()

    def on_selected_areas(self, *_):
        self._schedule_area_chips()

    def _schedule_area_render(self) -> None:
        Clock.schedule_once(lambda *_: self._render_area_options(), 0)
        try:
            popup = getattr(self, "_filter_popup", None)
        except Exception:
            popup = None
        if popup is not None:
            try:
                container = popup.ids.get("area_options_container")
                if container is not None:
                    Clock.schedule_once(lambda *_: self.render_area_options(container), 0)
            except Exception:
                pass

    def _schedule_area_chips(self) -> None:
        Clock.schedule_once(lambda *_: self._render_area_chips(), 0)

    def render_area_options(self, container=None) -> None:
        if container is None:
            try:
                container = (self.ids or {}).get("area_options_container")
            except Exception:
                container = None
        if container is None:
            return
        try:
            container.clear_widgets()
        except Exception:
            return

        state_ok = bool(self._norm_any(self.state_value))
        district_ok = bool(self._norm_any(self.district_value))
        if not state_ok or not district_ok:
            container.add_widget(
                Label(
                    text="Select State + District to load Areas.",
                    size_hint_y=None,
                    height=dp(32),
                    color=(1, 1, 1, 0.75),
                )
            )
            return

        options = [str(x).strip() for x in (self.area_options or []) if
                   str(x).strip() and str(x).strip().lower() != "any"]
        q = str(self.area_search or "").strip().lower()
        if q:
            options = [x for x in options if q in x.lower()]
        options = options[:80]
        if not options:
            container.add_widget(
                Label(text="No areas found.", size_hint_y=None, height=dp(32), color=(1, 1, 1, 0.75))
            )
            return

        selected = {str(x).strip() for x in (self.selected_areas or []) if str(x).strip()}
        for area in options:
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(38), spacing=dp(8))
            cb = CheckBox(active=(area in selected), size_hint=(None, None), size=(dp(32), dp(32)))
            lbl = Label(text=area, halign="left", valign="middle", color=(1, 1, 1, 0.92))
            # Do not force `text_size` to 0-width; it truncates to the first letter.
            lbl.size_hint_x = 1

            def _toggle(_cb, value, area=area):
                self.toggle_area(area, bool(value))

            cb.bind(active=_toggle)
            row.add_widget(cb)
            row.add_widget(lbl)
            container.add_widget(row)

    def _render_area_options(self) -> None:
        self.render_area_options()

    def _render_area_chips(self) -> None:
        try:
            container = (self.ids or {}).get("area_chips")
        except Exception:
            container = None
        if container is None:
            return
        try:
            container.clear_widgets()
        except Exception:
            return
        areas = [str(x).strip() for x in (self.selected_areas or []) if str(x).strip()]
        if not areas:
            return
        max_show = 12
        for area in areas[:max_show]:
            btn = Factory.AppButton(text=f"{area}  ✕")
            btn.size_hint = (None, None)
            btn.height = dp(32)

            def _resize(_btn, _):
                _btn.width = max(dp(90), _btn.texture_size[0] + dp(18))

            btn.bind(texture_size=_resize)
            _resize(btn, btn.texture_size)
            btn.bind(on_release=lambda _btn, a=area: self.remove_area(a))
            container.add_widget(btn)
        if len(areas) > max_show:
            lbl_more = Label(
                text=f"+{len(areas) - max_show} more",
                size_hint=(None, None),
                height=dp(32),
                color=(1, 1, 1, 0.75),
            )
            lbl_more.bind(
                texture_size=lambda _lbl, _ts: setattr(_lbl, "width", max(dp(70), _lbl.texture_size[0] + dp(12))))
            lbl_more.width = max(dp(70), lbl_more.texture_size[0] + dp(12))
            container.add_widget(lbl_more)

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
                set_session(
                    token=str(sess.get("token") or ""),
                    user=u,
                    remember=bool(sess.get("remember_me") or False),
                )
                pref_state = str(u.get("state") or "").strip()
                pref_district = str(u.get("district") or "").strip()

                def apply(*_):
                    self._apply_avatar(u)
                    try:
                        from kivy.app import App as _App

                        a = _App.get_running_app()
                        if a and hasattr(a, "sync_user_badge"):
                            a.sync_user_badge()  # type: ignore[attr-defined]
                    except Exception:
                        pass

                Clock.schedule_once(apply, 0)
            except Exception:
                return

        Thread(target=work, daemon=True).start()

    def _apply_avatar(self, u: dict[str, Any]) -> None:
        img = str(u.get("profile_image_url") or "").strip()
        self.profile_image_url = to_api_url(img) if img else ""

        name = str(
            u.get("name")
            or u.get("full_name")
            or u.get("username")
            or u.get("email")
            or ""
        ).strip()

        self.avatar_letter = name[0].upper() if name else "U"

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
        self.selected_areas = []
        self.area_search = ""

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
        self.selected_areas = []
        self.area_search = ""
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
    def _is_valid_gps(self, loc: Any) -> bool:
        try:
            if not loc:
                return False
            lat = float(loc[0])
            lon = float(loc[1])
            if abs(lat) < 1e-6 and abs(lon) < 1e-6:
                return False  # don't treat (0,0) as real GPS
            if abs(lat) > 90 or abs(lon) > 180:
                return False
            return True
        except Exception:
            return False

    def _ensure_gps_best_effort(self) -> None:
        def after(ok: bool) -> None:
            loc = get_last_known_location() if ok else None
            if self._is_valid_gps(loc):
                self._gps = (float(loc[0]), float(loc[1]))
                # Never show coordinates in the UI.
                self.gps_status = "GPS enabled (showing nearby results)."
                self.gps_msg = ""
            else:
                self._gps = None
                self.gps_status = "GPS not available (showing non-nearby results)."
                self.gps_msg = "" if ok else "GPS permission denied."

        ensure_permissions(required_location_permissions(), on_result=after)

    def enable_gps(self) -> None:
        print("🔥 ENABLE GPS BUTTON CLICKED")

        def after(ok: bool) -> None:
            print("🔥 GPS permission result:", ok)

            if not ok:
                self._gps = None
                self.gps_status = "GPS not available (showing non-nearby results)."
                self.gps_msg = "Location permission denied."
                return

            loc = get_last_known_location()
            print("🔥 GPS location:", loc)

            if self._is_valid_gps(loc):
                self._gps = (float(loc[0]), float(loc[1]))
                self.gps_status = "GPS enabled (showing nearby results)."
                self.gps_msg = ""
                Clock.schedule_once(lambda *_: self.refresh(), 0)
                return

            # ✅ ADD THIS UI STATE (WAITING MODE)
            self._gps = None
            self.gps_status = "Waiting for GPS signal…"
            self.gps_msg = "Turn ON Location and wait 10–30 seconds."
            open_location_settings()

        ensure_permissions(required_location_permissions(), on_result=after)

    def search_nearby_50km(self) -> None:
        """
        Explicit user action: show nearby results within 50km.
        """
        self.nearby_mode = True
        # Ensure radius is 50 for this mode (kept for compatibility).
        try:
            self.radius_km = "50"
        except Exception:
            pass
        self.enable_gps()

    def _feed_card(self, raw: dict[str, Any]) -> BoxLayout:
        p = raw or {}

        adv_no = str(p.get("adv_number") or p.get("ad_number") or p.get("id") or "").strip()

        owner_name = str(p.get("owner_name") or p.get("posted_by") or p.get("user_name") or "").strip()
        owner_initial = owner_name[:1].upper() if owner_name else "U"

        owner_image_raw = str(
            p.get("owner_image") or p.get("profile_image") or p.get("user_avatar") or ""
        ).strip()
        owner_image_url = to_api_url(owner_image_raw) if owner_image_raw else ""

        images = self._extract_media_items(p)
        already_contacted = bool(p.get("contacted"))
        is_my_posts = bool(p.get("_my_posts"))

        # -------------------------------------------------
        # META TEXT ONLY (NO TITLE)
        # -------------------------------------------------
        meta = " • ".join(
            x for x in [
                f"Ad #{adv_no}" if adv_no else "",
                p.get("rent_sale"),
                p.get("property_type"),
                p.get("price_display"),
                p.get("location_display"),
            ] if x
        )

        # =================================================
        # CARD ROOT
        # =================================================
        card = BoxLayout(
            orientation="vertical",
            padding=dp(12),
            spacing=dp(10),
            size_hint_y=None,
        )
        card.bind(minimum_height=lambda *_: setattr(card, "height", card.minimum_height))

        with card.canvas.before:
            Color(0, 0, 0, 0.35)
            rect = RoundedRectangle(pos=card.pos, size=card.size, radius=[16])
            Color(1, 1, 1, 0.12)
            border = Line(
                rounded_rectangle=[card.x, card.y, card.width, card.height, 16],
                width=1,
            )

        def _sync_bg(*_):
            rect.pos = card.pos
            rect.size = card.size
            border.rounded_rectangle = [card.x, card.y, card.width, card.height, 16]

        card.bind(pos=_sync_bg, size=_sync_bg)

        # =================================================
        # HEADER (Avatar + Meta ONLY)
        # =================================================
        header = BoxLayout(orientation="horizontal", spacing=dp(10), size_hint_y=None)
        header.bind(minimum_height=header.setter("height"))

        try:
            avatar = Factory.AvatarButton(size_hint=(None, None), size=(dp(44), dp(44)))
            avatar.image_source = owner_image_url
            avatar.fallback_text = owner_initial
            header.add_widget(avatar)
        except Exception:
            header.add_widget(Label(text=owner_initial, size_hint=(None, None), size=(dp(44), dp(44))))

        meta_lbl = Label(
            text=meta,
            size_hint_x=1,
            size_hint_y=None,
            color=(1, 1, 1, 0.78),
            halign="left",
            valign="middle",
        )

        def _resize_meta(*_):
            meta_lbl.text_size = (meta_lbl.width, None)
            meta_lbl.height = meta_lbl.texture_size[1] + dp(4)

        meta_lbl.bind(width=_resize_meta, texture_size=_resize_meta)
        Clock.schedule_once(_resize_meta, 0)

        header.add_widget(meta_lbl)
        card.add_widget(header)

        # =================================================
        # MEDIA (NO TOP GAP)
        # =================================================
        if images:
            urls = [
                to_api_url(str((it or {}).get("url") or "").strip())
                for it in (images or [])
                if str((it or {}).get("url") or "").strip()
            ]
            if urls:
                media_box = BoxLayout(orientation="vertical", size_hint_y=None)
                carousel = Carousel(direction="right", loop=True)
                carousel.size_hint = (1, None)
                carousel.height = _POST_MEDIA_MIN_H
                media_box.height = carousel.height

                imgs: list[AsyncImage] = []

                def _sync_media_h(*_):
                    media_box.height = carousel.height
                    for im in imgs:
                        im.height = carousel.height

                carousel.bind(height=_sync_media_h)

                def _recalc_height(*_):
                    if carousel.width <= 0:
                        return
                    target_h = float(_POST_MEDIA_MIN_H)
                    for im in imgs:
                        try:
                            tex = getattr(im, "texture", None)
                            if not tex:
                                continue
                            tw, th = tex.size
                            if not tw or not th:
                                continue
                            h = carousel.width * (float(th) / float(tw))
                            h = max(float(_POST_MEDIA_MIN_H), min(float(_POST_MEDIA_MAX_H), float(h)))
                            if h > target_h:
                                target_h = h
                        except Exception:
                            continue
                    carousel.height = float(target_h)

                carousel.bind(width=_recalc_height)

                for u in urls:
                    slide = BoxLayout()
                    img = AsyncImage(
                        source=u,
                        size_hint=(1, None),
                        height=carousel.height,
                        allow_stretch=True,
                        keep_ratio=True,
                    )
                    try:
                        setattr(img, "fit_mode", "cover")  # fill vertically
                    except Exception:
                        pass

                    slide.add_widget(img)
                    carousel.add_widget(slide)
                    imgs.append(img)
                    img.bind(texture=_recalc_height)

                media_box.add_widget(carousel)

                if len(urls) > 1:
                    btn_prev = Factory.AppButton(text="◀", size_hint=(None, None), size=(dp(44), dp(44)))
                    btn_next = Factory.AppButton(text="▶", size_hint=(None, None), size=(dp(44), dp(44)))
                    btn_row_nav = BoxLayout(size_hint_y=None, height=dp(44))
                    btn_prev.bind(on_release=lambda *_: carousel.load_previous())
                    btn_next.bind(on_release=lambda *_: carousel.load_next())
                    btn_row_nav.add_widget(btn_prev)
                    btn_row_nav.add_widget(btn_next)
                    media_box.add_widget(btn_row_nav)
                    media_box.height += dp(44)

                Clock.schedule_once(_recalc_height, 0)
                card.add_widget(media_box)

        # =================================================
        # ACTION HANDLERS
        # =================================================
        contact_lbl = Label(
            text=str((p or {}).get("contact_text") or "").strip(),
            size_hint_y=None,
            color=(1, 1, 1, 0.82),
            halign="left",
            valign="middle",
        )

        def _resize_contact(*_):
            contact_lbl.text_size = (contact_lbl.width, None)
            contact_lbl.height = (contact_lbl.texture_size[1] + dp(6)) if (contact_lbl.text or "").strip() else 0

        contact_lbl.bind(width=_resize_contact, texture_size=_resize_contact)
        Clock.schedule_once(_resize_contact, 0)

        def _set_contact_text(txt: str) -> None:
            try:
                p["contact_text"] = str(txt or "").strip()
            except Exception:
                pass
            contact_lbl.text = str(txt or "").strip()
            _resize_contact()

        def on_contact(_btn):
            if not self.is_logged_in:
                _popup("Login required", "Please login to contact the owner.")
                return
            pid = p.get("id")
            if not pid:
                _popup("Error", "Invalid property id.")
                return
            _btn.disabled = True

            from threading import Thread

            def work():
                try:
                    data = api_get_property_contact(pid) or {}
                    phone = str(data.get("phone") or "").strip()
                    email = str(data.get("email") or "").strip()
                    owner_name2 = str(data.get("owner_name") or "").strip()
                    company = str(data.get("owner_company_name") or "").strip()
                    parts = []
                    if owner_name2:
                        parts.append(owner_name2)
                    if company:
                        parts.append(company)
                    header_txt = " • ".join(parts).strip()
                    lines = []
                    if header_txt:
                        lines.append(f"[b]{header_txt}[/b]")
                    if phone:
                        lines.append(f"Phone: {phone}")
                    if email:
                        lines.append(f"Email: {email}")
                    contact_text = "\n".join(lines).strip()

                    def done(*_):
                        _btn.text = "View contact"
                        p["contacted"] = True
                        _set_contact_text(contact_text or "Contact unlocked.")
                        _btn.disabled = False

                    Clock.schedule_once(done, 0)
                except ApiError as e:
                    # Capture exception string outside the scheduled callback
                    # (Python clears exception variables after except blocks).
                    msg = str(e) or "Failed to unlock contact"

                    def fail(*_):
                        _btn.disabled = False
                        if _is_payment_required_msg(msg):
                            friendly = "Payment required. Please subscribe to unlock more contacts."
                            _set_contact_text(friendly)
                            _payment_required_popup(screen=self, detail="")
                            return
                        # Non-paywall errors: show inline + toast.
                        _set_contact_text(msg)
                        _popup("Error", msg)

                    Clock.schedule_once(fail, 0)
                except Exception as e:
                    msg = str(e) or "Failed to unlock contact"

                    def fail2(*_):
                        _btn.disabled = False
                        if _is_payment_required_msg(msg):
                            friendly = "Payment required. Please subscribe to unlock more contacts."
                            _set_contact_text(friendly)
                            _payment_required_popup(screen=self, detail="")
                            return
                        _set_contact_text(msg)
                        _popup("Error", msg)

                    Clock.schedule_once(fail2, 0)

            Thread(target=work, daemon=True).start()

        def on_share(_btn):
            subject = "Share Property"
            pid = p.get("id")
            url = to_api_url(f"/property/{pid}") if pid else ""
            body = "\n".join(x for x in [meta, url] if x)
            launched = share_text(subject=subject, text=body)

            from kivy.utils import platform
            if platform != "android":
                from kivy.core.clipboard import Clipboard
                Clipboard.copy(body)
                _popup("Share", "Copied to clipboard")
            elif not launched:
                _popup("Share", body)

        # =================================================
        # ACTION BUTTONS
        # =================================================
        btn_row = BoxLayout(orientation="horizontal", spacing=dp(10), size_hint_y=None, height=dp(44))

        if is_my_posts:
            btn_edit = Factory.AppButton(text="Edit", size_hint=(1, None), height=dp(44))
            btn_delete = Factory.AppButton(text="Delete", size_hint=(1, None), height=dp(44))
            btn_share = Factory.AppButton(text="Share", size_hint=(1, None), height=dp(44))

            btn_edit.bind(on_release=lambda *_: p.get("_on_edit", lambda: None)())
            btn_delete.bind(on_release=lambda *_: p.get("_on_delete", lambda: None)())
            btn_share.bind(on_release=on_share)

            btn_row.add_widget(btn_edit)
            btn_row.add_widget(btn_delete)
            btn_row.add_widget(btn_share)
        else:
            btn_contact = Factory.AppButton(
                text="View contact" if already_contacted else "Contact owner",
                size_hint=(1, None),
                height=dp(44),
                disabled=False,
            )
            btn_share = Factory.AppButton(text="Share", size_hint=(None, None), width=dp(96), height=dp(44))

            btn_contact.bind(on_release=on_contact)
            btn_share.bind(on_release=on_share)

            btn_row.add_widget(btn_contact)
            btn_row.add_widget(btn_share)

        # Inline contact details/status area (grows only when text is set).
        card.add_widget(contact_lbl)
        card.add_widget(btn_row)
        return card

    def _extract_media_items(self, p: dict[str, Any]) -> list[dict[str, Any]]:
        src = None
        try:
            if isinstance(p.get("images"), list):
                src = p.get("images")
            elif isinstance(p.get("image_urls"), list):
                src = p.get("image_urls")
            elif isinstance(p.get("media"), list):
                src = p.get("media")
            elif isinstance(p.get("photos"), list):
                src = p.get("photos")
            elif isinstance(p.get("files"), list):
                src = p.get("files")
        except Exception:
            src = None

        items = list(src or [])
        out: list[dict[str, Any]] = []

        def _guess_type(url: str) -> str:
            u = (url or "").lower()
            for ext in (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"):
                if u.endswith(ext):
                    return "video/*"
            return "image/*"

        for it in items:
            if isinstance(it, str):
                url = it.strip()
                if not url:
                    continue
                out.append({"url": url, "content_type": _guess_type(url)})
                continue
            if isinstance(it, dict):
                url = str(
                    it.get("url")
                    or it.get("image_url")
                    or it.get("imageUrl")
                    or it.get("src")
                    or it.get("path")
                    or it.get("image")
                    or ""
                ).strip()
                if not url:
                    continue
                ctype = str(it.get("content_type") or it.get("contentType") or "").strip()
                if not ctype:
                    ctype = _guess_type(url)
                out.append({"url": url, "content_type": ctype})
                continue
        return out

    def _load_need_categories(self):
        from threading import Thread

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
                    flat = data.get("flat_items") or []
                    for it in flat:
                        label = str((it or {}).get("label") or "").strip()
                        if label:
                            values.append(label)

                seen: set[str] = set()
                deduped: list[str] = []
                for v in values:
                    if v in seen:
                        continue
                    seen.add(v)
                    deduped.append(v)

                def apply(*_):
                    self.need_values = deduped
                    self.need_values_filtered = list(deduped)

                Clock.schedule_once(apply, 0)
            except Exception:
                return

        Thread(target=work, daemon=True).start()

    def refresh(self):
        if self.is_loading:
            return
        self.is_loading = True
        self.error_msg = ""

        from threading import Thread

        def work():
            try:
                # -----------------------------
                # Build filters
                # -----------------------------
                need = (self.need_category or "").strip()
                q = need if need and need.lower() != "any" else ""
                post_group = str(getattr(self, "post_group", "") or "").strip().lower()

                rent_sale_norm = self._norm_any(self.rent_sale)

                max_price = (self.max_price or "").strip()
                if max_price and not max_price.isdigit():
                    max_price = ""

                state = self._norm_any(self.state_value)
                district = self._norm_any(self.district_value)

                sel = [str(x).strip() for x in (self.selected_areas or []) if str(x).strip()]
                area = ",".join(sel) if sel else self._norm_any(self.area_value)

                sort_budget = (self.sort_budget or "").strip().lower()
                sort_budget_param = ""
                if sort_budget.startswith("top"):
                    sort_budget_param = "top"
                elif sort_budget.startswith("bottom"):
                    sort_budget_param = "bottom"

                # -----------------------------
                # GPS / Nearby logic
                # -----------------------------
                loc = getattr(self, "_gps", None)

                # 🔒 HARD DEFAULT = 50 KM
                radius = 50

                use_nearby = bool(getattr(self, "nearby_mode", False))
                if use_nearby and loc:
                    data = api_list_nearby_properties(
                        lat=float(loc[0]),
                        lon=float(loc[1]),
                        radius_km=radius,
                        q=q,
                        post_group=post_group,
                        rent_sale=rent_sale_norm,
                        max_price=max_price,
                        state=state,
                        district=district,
                        area=area,
                        posted_within_days="",
                        limit=20,
                    )
                else:
                    data = api_list_properties(
                        q=q,
                        post_group=post_group,
                        rent_sale=rent_sale_norm,
                        max_price=max_price,
                        state=state,
                        district=district,
                        area=area,
                        sort_budget=sort_budget_param,
                        posted_within_days="",
                    )

                # -----------------------------
                # Build cards
                # -----------------------------
                cards: list[dict[str, Any]] = []
                for pp in (data.get("items") or []):
                    cards.append(
                        {
                            "id": int(pp.get("id") or 0),
                            "title": str(pp.get("title") or "Property"),
                            "price": str(pp.get("price_display") or pp.get("price") or ""),
                            "location": str(pp.get("location_display") or pp.get("location") or ""),
                            "kind": str(pp.get("property_type") or ""),
                            "rent_sale": str(pp.get("rent_sale") or ""),
                            "raw": pp,
                        }
                    )

                def done(*_):
                    self.items = cards
                    try:
                        container = self.ids.get("list_container")
                        if container is not None:
                            container.clear_widgets()
                            for c in cards:
                                container.add_widget(self._feed_card(c.get("raw") or {}))
                    except Exception:
                        pass

                    # Show empty-nearby message only when nearby mode is ON.
                    if use_nearby and loc and not cards:
                        self.error_msg = "No properties found within 50 km."

                    self.is_loading = False

                Clock.schedule_once(done, 0)

            except ApiError as e:
                err_msg = str(e)
                Clock.schedule_once(lambda *_: setattr(self, "error_msg", err_msg), 0)
                Clock.schedule_once(lambda *_: _popup("Error", err_msg), 0)
                Clock.schedule_once(lambda *_: setattr(self, "is_loading", False), 0)

        Thread(target=work, daemon=True).start()

    def go_profile(self):
        return self.go_settings()

    def go_owner(self):
        if not self.is_logged_in:
            _popup("Login required", "Please login to publish an ad.")
            if self.manager:
                self.manager.current = "login"
            return
        u = get_user() or {}
        role = (u.get("role") or "").lower().strip()
        if role not in {"user", "owner", "admin"}:
            _popup("Login required", "Please login with a valid account to publish ads.")
            return
        if self.manager:
            # Ensure publish form is in "new post" mode.
            try:
                scr = self.manager.get_screen("owner_add_property")
                if hasattr(scr, "start_new"):
                    scr.start_new()  # type: ignore[attr-defined]
                elif hasattr(scr, "start_edit"):
                    scr.start_edit({})  # type: ignore[attr-defined]
            except Exception:
                pass
            self.manager.current = "owner_add_property"

    @staticmethod
    def go_admin():
        _popup("Not available", "Admin entry is hidden in the app UI.")

    def gesture_refresh_enabled(self) -> bool:
        return True

