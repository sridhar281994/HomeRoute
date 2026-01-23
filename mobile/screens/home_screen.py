from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.factory import Factory
from kivy.metrics import dp
from kivy.properties import (
    BooleanProperty,
    ListProperty,
    ObjectProperty,
    StringProperty,
)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.checkbox import CheckBox
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import AsyncImage
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
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
                lbl.text_size = (0, None)

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
                grid.add_widget(Label(text="No areas available.", size_hint_y=None, height=dp(32), color=(1, 1, 1, 0.75)))

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


class HomeHamburgerMenu(ModalView):
    """
    Full-screen modal overlay that anchors a small dropdown panel under the
    hamburger button. Auto-dismisses on outside tap and animates open (slide+fade).
    """

    def __init__(self, home: "HomeScreen", anchor_widget: Widget, **kwargs):
        super().__init__(**kwargs)
        self._home = home
        self._anchor = anchor_widget
        self.size_hint = (1, 1)
        self.auto_dismiss = True
        self.background = ""
        self.background_color = (0, 0, 0, 0)

        # Root overlay that covers the screen; tapping outside the panel dismisses.
        root = FloatLayout()
        self._panel = BoxLayout(
            orientation="vertical",
            size_hint=(None, None),
            padding=dp(10),
            spacing=dp(8),
        )
        self._panel.bind(minimum_height=self._panel.setter("height"))

        # Panel background + border (match the app theme).
        from kivy.graphics import Color, Line, RoundedRectangle

        with self._panel.canvas.before:
            Color(1, 1, 1, 0.14)
            self._bg = RoundedRectangle(pos=self._panel.pos, size=self._panel.size, radius=[dp(16)])
            Color(1, 1, 1, 0.12)
            self._border = Line(rounded_rectangle=[0, 0, 0, 0, dp(16)], width=1.0)

        def _sync_panel_bg(*_):
            self._bg.pos = self._panel.pos
            self._bg.size = self._panel.size
            self._border.rounded_rectangle = [self._panel.x, self._panel.y, self._panel.width, self._panel.height, dp(16)]

        self._panel.bind(pos=_sync_panel_bg, size=_sync_panel_bg)

        # Menu items (use existing navigation helpers on HomeScreen).
        items: list[tuple[str, str]] = [
            ("Home", "home"),
            ("My Posts", "my_posts"),
            ("Settings", "settings"),
            ("Subscription", "subscription"),
            ("Publish Ad", "publish"),
            ("Logout", "logout"),
        ]

        for label, key in items:
            btn = Factory.AppButton(text=label)
            btn.size_hint_y = None
            btn.height = dp(44)
            # Make logout visually distinct.
            if key == "logout":
                btn.color = (0.94, 0.27, 0.27, 1)
            btn.bind(on_release=lambda _btn, key=key: self._select(key))
            self._panel.add_widget(btn)

        root.add_widget(self._panel)
        self.add_widget(root)

        # Track state so HomeScreen can toggle the menu.
        self.bind(on_dismiss=lambda *_: setattr(self._home, "_hamburger_menu", None))

    def on_open(self, *args):
        # After layout pass, compute anchor position and animate in.
        Clock.schedule_once(lambda *_: self._position_and_animate(), 0)
        return super().on_open(*args)

    def _position_and_animate(self) -> None:
        # Panel width responsive to screen size.
        w = min(dp(260), Window.width * 0.78)
        self._panel.width = w
        # Ensure height is computed from children.
        self._panel.height = max(self._panel.minimum_height, dp(44))

        # Anchor position (window coords): use the bottom-left of the hamburger button.
        try:
            ax, ay = self._anchor.to_window(self._anchor.x, self._anchor.y)
            ah = float(getattr(self._anchor, "height", dp(44)))
        except Exception:
            ax, ay, ah = (dp(12), Window.height - dp(60), dp(44))

        # Place dropdown directly below the button.
        top = ay - dp(6)
        x_target = ax
        y_target = top - self._panel.height

        # Keep on-screen (still prefers "below").
        x_target = max(dp(8), min(x_target, Window.width - self._panel.width - dp(8)))
        y_target = max(dp(8), min(y_target, Window.height - self._panel.height - dp(8)))

        # Start slightly above and transparent, then slide down + fade in.
        self._panel.opacity = 0.0
        self._panel.pos = (x_target, y_target + dp(14))
        Animation.cancel_all(self._panel)
        Animation(opacity=1.0, y=y_target, d=0.18, t="out_quad").start(self._panel)

    def _select(self, key: str) -> None:
        # Close first, then navigate (keeps UX snappy and avoids stray touches).
        try:
            self.dismiss()
        except Exception:
            pass

        def nav(*_):
            if key == "home":
                self._home.go_home()
            elif key == "my_posts":
                self._home.go_my_posts()
            elif key == "settings":
                self._home.go_settings()
            elif key == "subscription":
                self._home.go_subscription()
            elif key == "publish":
                self._home.go_publish_ad()
            elif key == "logout":
                self._home.do_logout()

        Clock.schedule_once(nav, 0)


class HomeScreen(GestureNavigationMixin, Screen):
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
    selected_areas = ListProperty([])
    area_search = StringProperty("")
    radius_km = StringProperty("20")
    gps_status = StringProperty("GPS not available (showing non-nearby results).")
    gps_msg = StringProperty("")
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
        Clock.schedule_once(lambda _dt: self._render_area_options(), 0)
        Clock.schedule_once(lambda _dt: self._render_area_chips(), 0)

        # Best-effort: refresh user profile for latest location (non-fatal).
        if self.is_logged_in:
            self._refresh_profile_from_server()

        # Best-effort GPS capture (non-fatal); refresh once it becomes available.
        self._ensure_gps_best_effort()

        Clock.schedule_once(lambda _dt: self.refresh(), 0)
        # Enable gesture capture even when ScrollView consumes touches.
        self.gesture_bind_window()

    def on_leave(self, *args):
        # Close any open hamburger menu overlay when navigating away.
        try:
            menu = getattr(self, "_hamburger_menu", None)
            if menu is not None:
                menu.dismiss()
                self._hamburger_menu = None
        except Exception:
            pass
        # Avoid leaking Window bindings when screen is not visible.
        try:
            self.gesture_unbind_window()
        except Exception:
            pass
        return super().on_leave(*args)

    def open_hamburger_menu(self, anchor_widget: Widget) -> None:
        """
        Toggle the Home hamburger dropdown menu.
        """
        try:
            menu = getattr(self, "_hamburger_menu", None)
        except Exception:
            menu = None
        if menu is not None:
            try:
                menu.dismiss()
            except Exception:
                pass
            self._hamburger_menu = None
            return

        try:
            menu = HomeHamburgerMenu(home=self, anchor_widget=anchor_widget)
            self._hamburger_menu = menu
            menu.open()
        except Exception:
            # Never crash the Home screen due to menu rendering errors.
            return

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
            if self.manager:
                self.manager.current = "welcome"
            return
        clear_session()
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

    def _schedule_area_chips(self) -> None:
        Clock.schedule_once(lambda *_: self._render_area_chips(), 0)

    def _render_area_options(self) -> None:
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

        options = [str(x).strip() for x in (self.area_options or []) if str(x).strip() and str(x).strip().lower() != "any"]
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
            lbl.text_size = (0, None)

            def _toggle(_cb, value, area=area):
                self.toggle_area(area, bool(value))

            cb.bind(active=_toggle)
            row.add_widget(cb)
            row.add_widget(lbl)
            container.add_widget(row)

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
            lbl_more.bind(texture_size=lambda _lbl, _ts: setattr(_lbl, "width", max(dp(70), _lbl.texture_size[0] + dp(12))))
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
        """
        Manual action from Home screen button.
        """
        def after(ok: bool) -> None:
            # Always log so we can debug issues via `adb logcat` / console output.
            try:
                print("[GPS] Enable GPS pressed. permission_ok=", bool(ok))
            except Exception:
                pass

            if not ok:
                self._gps = None
                self.gps_status = "GPS not available (showing non-nearby results)."
                self.gps_msg = "Location permission denied."
                return

            loc = get_last_known_location()
            try:
                print("[GPS] last_known_location=", loc)
            except Exception:
                pass

            if self._is_valid_gps(loc):
                self._gps = (float(loc[0]), float(loc[1]))
                self.gps_status = "GPS enabled (showing nearby results)."
                self.gps_msg = ""
                # Immediately refresh so the user sees nearby results.
                Clock.schedule_once(lambda *_: self.refresh(), 0)
                return

            # Permissions are granted, but we have no fix yet (often because Location is OFF).
            self._gps = None
            self.gps_status = "GPS is off (showing non-nearby results)."
            self.gps_msg = "Turn on Location/GPS in settings, then tap Enable GPS again."
            open_location_settings()

        ensure_permissions(required_location_permissions(), on_result=after)

    def feed_card(self, raw: dict[str, Any]) -> BoxLayout:
        """
        Public wrapper to build a feed card.

        Other screens (e.g. My Posts) call this method to reuse the layout without
        reaching into a protected member.
        """
        return self._feed_card(raw)

    def _feed_card(self, raw: dict[str, Any]) -> BoxLayout:
        """
        Build a feed card roughly matching the web UI:
        title/meta header, optional media preview, and an action button.
        """
        p = raw or {}
        title = str(p.get("title") or "Property").strip()
        adv_no = str(p.get("adv_number") or p.get("ad_number") or p.get("id") or "").strip()
        distance_txt = ""
        try:
            dist_raw = p.get("distance_km")
            if dist_raw is not None:
                dist = float(dist_raw)
                if dist >= 0:
                    distance_txt = f"{dist:.1f}km from you" if dist < 10 else f"{round(dist)}km from you"
        except Exception:
            distance_txt = ""
        created_txt = ""
        try:
            created_raw = str(p.get("created_at") or "").strip()
            if created_raw:
                if created_raw.endswith("Z"):
                    created_raw = created_raw[:-1] + "+00:00"
                dt = datetime.fromisoformat(created_raw)
                created_txt = dt.date().isoformat()
        except Exception:
            created_txt = ""
        meta = " • ".join(
            [
                x
                for x in [
                    distance_txt,
                    f"Ad #{adv_no}" if adv_no else "",
                    str(p.get("rent_sale") or ""),
                    str(p.get("property_type") or ""),
                    str(p.get("price_display") or ""),
                    str(p.get("location_display") or ""),
                    created_txt,
                ]
                if x
            ]
        )
        images = p.get("images") or []
        already_contacted = bool(p.get("contacted"))

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

        def do_share(*_):
            try:
                pid_raw = p.get("id")
                pid = int(str(pid_raw).strip()) if pid_raw is not None else 0
            except Exception:
                pid = 0
            title_s = str(p.get("title") or "Property").strip()
            adv = str(p.get("adv_number") or p.get("ad_number") or pid or "").strip()
            meta_lines = []
            for x in [
                str(p.get("rent_sale") or "").strip(),
                str(p.get("property_type") or "").strip(),
                str(p.get("price_display") or "").strip(),
                str(p.get("location_display") or "").strip(),
            ]:
                if x:
                    meta_lines.append(x)
            # Prefer linking to the web UI route if hosted on the same domain.
            api_link = to_api_url(f"/property/{pid}") if pid else ""
            img_link = ""
            try:
                imgs = p.get("images") or []
                if imgs:
                    img_link = to_api_url(str((imgs[0] or {}).get("url") or "").strip())
            except Exception:
                img_link = ""
            subject = f"{title_s} (Ad #{adv})" if adv else title_s
            body = "\n".join(
                [x for x in [title_s, (" • ".join(meta_lines) if meta_lines else ""), api_link, (f"Image: {img_link}" if img_link else "")] if x]
            )

            launched = share_text(subject=subject, text=body)
            if launched:
                _popup("Share", "Choose an app to share this post.")
                return
            try:
                from kivy.core.clipboard import Clipboard

                Clipboard.copy(body)
                _popup("Share", "Copied share text to clipboard.")
            except Exception:
                _popup("Share", body)

        header = BoxLayout(orientation="horizontal", spacing=10, size_hint_y=None, height=dp(52))

        avatar = Label(
            text=(title[:1].upper() if title else "A"),
            size_hint=(None, None),
            size=(dp(42), dp(42)),
            halign="center",
            valign="middle",
            color=(1, 1, 1, 0.95),
        )
        avatar.text_size = avatar.size
        with avatar.canvas.before:
            Color(0.66, 0.33, 0.97, 0.95)
            av_bg = RoundedRectangle(pos=avatar.pos, size=avatar.size, radius=[dp(21)])

        def _sync_avatar(*_):
            av_bg.pos = avatar.pos
            av_bg.size = avatar.size

        avatar.bind(pos=_sync_avatar, size=_sync_avatar)
        header.add_widget(avatar)

        hb = BoxLayout(orientation="vertical", spacing=dp(2))
        lbl_title = Label(
            text=f"[b]{title}[/b]",
            size_hint_y=None,
            height=dp(24),
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="right",
        )
        lbl_meta = Label(
            text=str(meta),
            size_hint_y=None,
            height=dp(22),
            color=(1, 1, 1, 0.78),
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="right",
        )

        def _sync_label(_lbl: Label, *_):
            try:
                _lbl.text_size = (_lbl.width, None)
            except Exception:
                pass

        lbl_title.bind(size=_sync_label)
        lbl_meta.bind(size=_sync_label)
        _sync_label(lbl_title)
        _sync_label(lbl_meta)

        hb.add_widget(lbl_title)
        hb.add_widget(lbl_meta)
        header.add_widget(hb)
        header.add_widget(Widget())
        btn_share = Factory.AppButton(
            text="[font=EmojiFont]↗️[/font]",
            size_hint=(None, None),
            width=dp(56),
            height=dp(40),
        )
        btn_share.bind(on_release=do_share)
        header.add_widget(btn_share)
        card.add_widget(header)

        card.add_widget(Label(text="[b]Photos[/b]", size_hint_y=None, height=22))
        # Match web UI tile height (HomePage uses ~220px preview tiles).
        thumb_h = dp(220)
        if images:
            # Show up to 6 items as a 2-column grid (roughly like the web HomePage).
            media = list(images)[:6]
            grid = GridLayout(cols=2, spacing=dp(8), size_hint_y=None)
            rows = (len(media) + 1) // 2
            grid.height = rows * thumb_h + max(0, rows - 1) * dp(8)

            for it in media:
                it = it or {}
                ctype = str(it.get("content_type") or "").lower()
                # Older rows may not have content_type set. Treat unknown/blank types as images.
                if ctype.startswith("video/"):
                    grid.add_widget(Label(text="(Video)", size_hint_y=None, height=thumb_h, color=(1, 1, 1, 0.78)))
                else:
                    img = AsyncImage(source=to_api_url(it.get("url") or ""), allow_stretch=True, keep_ratio=False)
                    img.size_hint_y = None
                    img.height = thumb_h
                    grid.add_widget(img)

            card.add_widget(grid)
        else:
            grid = GridLayout(cols=2, spacing=dp(8), size_hint_y=None)
            grid.height = thumb_h

            def _placeholder_tile() -> BoxLayout:
                tile = BoxLayout(size_hint_y=None, height=thumb_h)
                with tile.canvas.before:
                    Color(0, 0, 0, 0.22)
                    rect = RoundedRectangle(pos=tile.pos, size=tile.size, radius=[dp(12)])
                    Color(1, 1, 1, 0.12)
                    border = Line(
                        rounded_rectangle=[tile.x, tile.y, tile.width, tile.height, dp(12)],
                        width=1.0,
                    )

                def _sync_tile(*_):
                    rect.pos = tile.pos
                    rect.size = tile.size
                    border.rounded_rectangle = [tile.x, tile.y, tile.width, tile.height, dp(12)]

                tile.bind(pos=_sync_tile, size=_sync_tile)
                return tile

            grid.add_widget(_placeholder_tile())
            grid.add_widget(_placeholder_tile())
            card.add_widget(grid)
            card.add_widget(Label(text="No Photos", size_hint_y=None, height=22, color=(1, 1, 1, 0.78)))

        amenities = [str(x).strip() for x in (p.get("amenities") or []) if str(x).strip()]
        if amenities:
            card.add_widget(Label(text="[b]Amenities[/b]", size_hint_y=None, height=22))
            card.add_widget(
                Label(
                    text=", ".join(amenities),
                    size_hint_y=None,
                    height=36,
                    color=(1, 1, 1, 0.85),
                )
            )

        btn_row = BoxLayout(orientation="horizontal", spacing=10, size_hint_y=None, height=44)
        btn_contact = Factory.AppButton(
            text="Contacted" if already_contacted else "Contact owner",
            size_hint_y=None,
            height=44,
        )
        btn_contact.disabled = already_contacted
        lbl_status = Label(text="", size_hint_y=None, height=40, color=(1, 1, 1, 0.85))
        if already_contacted:
            lbl_status.text = "Contact details already sent."

        def do_contact(*_):
            sess = get_session() or {}
            if not (sess.get("token") or ""):
                lbl_status.text = "Login required to contact owner."
                if self.manager:
                    self.manager.current = "login"
                return
            pid_raw = p.get("id")
            try:
                pid = int(str(pid_raw).strip())
            except (TypeError, ValueError):
                lbl_status.text = "Invalid ad id."
                return
            if pid <= 0:
                lbl_status.text = "Invalid ad id."
                return
            btn_contact.disabled = True

            from threading import Thread

            def work():
                try:
                    contact = api_get_property_contact(pid)
                    owner_name = str(contact.get("owner_name") or "").strip()
                    adv_no_inner = str(contact.get("adv_number") or contact.get("advNo") or pid).strip()
                    who = f" ({owner_name})" if owner_name else ""

                    def done(*_dt):
                        p["contacted"] = True
                        btn_contact.text = "Contacted"
                        lbl_status.text = (
                            f"Contact details sent to your registered email/SMS for Ad #{adv_no_inner}{who}."
                        )

                    Clock.schedule_once(done, 0)
                except ApiError as e:
                    err_msg = str(e) or "Locked"

                    def fail(*_dt):
                        btn_contact.disabled = False
                        lbl_status.text = err_msg

                    Clock.schedule_once(fail, 0)

            Thread(target=work, daemon=True).start()

        btn_contact.bind(on_release=do_contact)
        btn_row.add_widget(btn_contact)
        card.add_widget(btn_row)
        card.add_widget(lbl_status)

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
                    self.need_values_filtered = list(deduped)
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

    def apply_need_filter(self) -> None:
        """
        Filter need_values based on need_search (searchable category picker).
        """
        try:
            q = str(self.need_search or "").strip().lower()
        except Exception:
            q = ""
        values = list(self.need_values or [])
        if not q:
            self.need_values_filtered = values
            return
        out: list[str] = []
        for v in values:
            s = str(v or "").strip()
            if not s:
                continue
            if s.lower() == "any":
                continue
            if q in s.lower():
                out.append(s)
        self.need_values_filtered = ["Any"] + out

    def on_need_input_changed(self, widget) -> None:
        """
        Single "Need category" control:
        - user types into TextInput
        - dropdown suggestions appear while typing (scrollable)
        - selecting a suggestion fills the same input
        """
        try:
            if getattr(self, "_suppress_need_dropdown", False):
                return
            text = str(getattr(widget, "text", "") or "").strip()
            # Keep "Any" as the empty/default semantic.
            self.need_category = text or "Any"
            self.need_search = text
            self.apply_need_filter()
            if getattr(widget, "focus", False):
                self._open_need_dropdown(widget)
        except Exception:
            return

    def on_need_input_focus(self, widget, focused: bool) -> None:
        try:
            if getattr(self, "_suppress_need_dropdown", False):
                return
            if focused:
                # Show options immediately on focus.
                self.need_search = str(getattr(widget, "text", "") or "").strip()
                self.apply_need_filter()
                self._open_need_dropdown(widget)
            else:
                dd = getattr(self, "_need_dropdown", None)
                if dd is not None:
                    dd.dismiss()
        except Exception:
            return

    def _select_need_value(self, value: str, widget) -> None:
        from kivy.clock import Clock

        v = str(value or "").strip() or "Any"
        self.need_category = v
        self.need_search = "" if v.lower() == "any" else v
        self.apply_need_filter()
        self._suppress_need_dropdown = True
        try:
            widget.text = "" if v.lower() == "any" else v
        except Exception:
            pass
        dd = getattr(self, "_need_dropdown", None)
        if dd is not None:
            dd.dismiss()

        def _unsuppress(*_):
            self._suppress_need_dropdown = False

        Clock.schedule_once(_unsuppress, 0.15)

    def _open_need_dropdown(self, widget) -> None:
        from kivy.metrics import dp
        from kivy.uix.button import Button
        from kivy.uix.dropdown import DropDown

        dd = getattr(self, "_need_dropdown", None)
        if dd is not None:
            try:
                dd.dismiss()
            except Exception:
                pass
            try:
                dd.clear_widgets()
            except Exception:
                pass
        dd = DropDown(auto_width=False)
        dd.width = getattr(widget, "width", dp(320))
        dd.max_height = dp(260)

        values = list(self.need_values_filtered or []) or ["Any"]
        # Cap to keep the dropdown responsive.
        for raw in values[:160]:
            label = str(raw or "").strip()
            if not label:
                continue
            btn = Button(text=label, size_hint_y=None, height=dp(44))
            btn.bind(on_release=lambda _btn, v=label: self._select_need_value(v, widget))
            dd.add_widget(btn)

        self._need_dropdown = dd
        try:
            dd.open(widget)
        except Exception:
            pass

    def refresh(self):
        if self.is_loading:
            return
        self.is_loading = True
        self.error_msg = ""

        def work():
            try:
                need = (self.need_category or "").strip()
                q = need if need and need.lower() != "any" else ""
                rent_sale_norm = self._norm_any(self.rent_sale)
                max_price = (self.max_price or "").strip()
                # Defensive: only send numeric max_price (avoid backend int parse errors).
                if max_price and not max_price.isdigit():
                    max_price = ""
                state = self._norm_any(self.state_value)
                district = self._norm_any(self.district_value)
                sel = [str(x).strip() for x in (self.selected_areas or []) if str(x).strip()]
                area = ",".join(sel) if sel else self._norm_any(self.area_value)

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
                        rent_sale=rent_sale_norm,
                        max_price=max_price,
                        state=state,
                        district=district,
                        area=area,
                        posted_within_days=posted_param,
                        limit=20,
                    )
                    # Nearby results require ads to have GPS coords. If none match (common),
                    # fall back to normal listing so refresh never "empties" the Home feed.
                    nearby_items = data.get("items") or []
                    if not nearby_items:
                        data = api_list_properties(
                            q=q,
                            rent_sale=rent_sale_norm,
                            max_price=max_price,
                            state=state,
                            district=district,
                            area=area,
                            sort_budget=sort_budget_param,
                            posted_within_days=posted_param,
                        )
                else:
                    data = api_list_properties(
                        q=q,
                        rent_sale=rent_sale_norm,
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
                err_msg = str(e)
                Clock.schedule_once(lambda *_: setattr(self, "error_msg", err_msg), 0)
                Clock.schedule_once(lambda *_dt, err_msg=err_msg: _popup("Error", err_msg), 0)
                Clock.schedule_once(lambda *_: setattr(self, "is_loading", False), 0)

        from threading import Thread

        Thread(target=work, daemon=True).start()

    # -----------------------
    # Gestures (pull-to-refresh)
    # -----------------------
    def gesture_can_refresh(self) -> bool:
        """
        Only allow pull-to-refresh if the feed scroll view is already at the top.
        """
        try:
            if self.is_loading:
                return False
            sv = self.ids.get("feed_scroll")
            if sv is None:
                return False
            # Kivy ScrollView: scroll_y == 1 means top.
            return float(getattr(sv, "scroll_y", 0.0) or 0.0) >= 0.99
        except Exception:
            return False

    def gesture_refresh(self) -> None:
        # Mirror the explicit Refresh button behavior.
        try:
            print("[GESTURE] pull-to-refresh")
        except Exception:
            pass
        self.refresh()

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
            # Ensure the publish form is in "new post" mode (not edit).
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
        # Removed from home page UI; keep method for backward KV compatibility.
        _popup("Not available", "Admin entry is hidden in the app UI.")

