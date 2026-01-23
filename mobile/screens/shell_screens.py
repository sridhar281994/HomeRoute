from __future__ import annotations

import os
from typing import Any

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.factory import Factory
from kivy.metrics import dp
from kivy.properties import BooleanProperty, DictProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.button import Button
from kivy.uix.screenmanager import Screen

from screens.gestures import GestureNavigationMixin
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
    api_owner_update_property,
    api_subscription_status,
    api_upload_property_media,
    to_api_url,
)
from frontend_app.utils.share import share_text
from frontend_app.utils.storage import clear_session, get_session, get_user, set_guest_session, set_session
from frontend_app.utils.android_permissions import ensure_permissions, required_location_permissions, required_media_permissions
from frontend_app.utils.android_location import get_last_known_location
from frontend_app.utils.android_filepicker import ensure_local_paths, is_image_path, is_video_path


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


def _default_media_dir() -> str:
    """
    Best-effort starting directory for image/video pickers on Android.

    We avoid `~` because on Android it points to the app's private storage,
    which may contain the packaged source tree (looks like the repo).
    """
    try:
        from kivy.utils import platform

        if platform != "android":
            return os.path.expanduser("~")
    except Exception:
        return os.path.expanduser("~")

    # Try Android public media dirs first (Pictures/DCIM).
    try:
        from jnius import autoclass  # type: ignore

        Environment = autoclass("android.os.Environment")
        pictures = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES)
        if pictures is not None:
            p = str(pictures.getAbsolutePath() or "").strip()
            if p and os.path.isdir(p):
                return p
    except Exception:
        pass

    for p in [
        "/storage/emulated/0/Pictures",
        "/storage/emulated/0/DCIM",
        "/sdcard/Pictures",
        "/sdcard/DCIM",
        "/storage/emulated/0/Download",
        "/sdcard/Download",
    ]:
        try:
            if os.path.isdir(p):
                return p
        except Exception:
            continue

    # Fallback: external storage root if present.
    for p in ["/storage/emulated/0", "/sdcard"]:
        try:
            if os.path.isdir(p):
                return p
        except Exception:
            continue

    return os.path.expanduser("~")


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}


def _candidate_media_roots() -> list[str]:
    """
    Best-effort media roots for Android.
    We deliberately avoid showing paths in the UI; this is used only for scanning.
    """
    roots: list[str] = []
    for p in [
        _default_media_dir(),
        "/storage/emulated/0/Pictures",
        "/storage/emulated/0/DCIM",
        "/sdcard/Pictures",
        "/sdcard/DCIM",
        "/storage/emulated/0/Download",
        "/sdcard/Download",
    ]:
        try:
            if p and os.path.isdir(p):
                ap = os.path.abspath(p)
                if ap not in roots:
                    roots.append(ap)
        except Exception:
            continue
    return roots


def _collect_media_files(*, roots: list[str], include_videos: bool, max_items: int = 600) -> list[str]:
    """
    Recursively collects media files (newest first) from common user folders.
    Returns absolute file paths. Caps results for performance.
    """
    found: list[tuple[float, str]] = []
    for root in roots:
        try:
            for dirpath, _dirnames, filenames in os.walk(root):
                for fn in filenames:
                    try:
                        ext = os.path.splitext(fn.lower())[1]
                        if ext in _IMAGE_EXTS or (include_videos and ext in _VIDEO_EXTS):
                            fp = os.path.join(dirpath, fn)
                            try:
                                mtime = os.path.getmtime(fp)
                            except Exception:
                                mtime = 0.0
                            found.append((float(mtime), fp))
                    except Exception:
                        continue
        except Exception:
            continue

    # Newest first
    found.sort(key=lambda t: t[0], reverse=True)
    out: list[str] = []
    seen: set[str] = set()
    for _mt, fp in found:
        if fp in seen:
            continue
        seen.add(fp)
        out.append(fp)
        if len(out) >= int(max_items):
            break
    return out


class _MediaGridPickerPopup(Popup):
    """
    Grid-only picker (no filenames, no path labels).
    - Settings (profile image): single-tap to select + upload.
    - Publish Ad: multiselect with limits.
    """

    def __init__(
        self,
        *,
        title: str,
        include_videos: bool,
        multiselect: bool,
        on_done,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.title = title
        self.size_hint = (0.96, 0.94)
        self.auto_dismiss = False
        self._include_videos = bool(include_videos)
        self._multiselect = bool(multiselect)
        self._on_done = on_done
        self._selected: set[str] = set()
        self._media: list[str] = []

        root = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))

        # Lightweight header: status only (no filesystem paths).
        self._status = Label(text="Loading photos…", size_hint_y=None, height=dp(22), color=(1, 1, 1, 0.78))
        root.add_widget(self._status)

        self._scroll = ScrollView(do_scroll_x=False, bar_width=dp(6))
        self._grid = GridLayout(cols=3, spacing=dp(8), size_hint_y=None)
        self._grid.bind(minimum_height=self._grid.setter("height"))
        self._scroll.add_widget(self._grid)
        root.add_widget(self._scroll)

        footer = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(10))
        btn_cancel = Factory.AppButton(text="Cancel", color=(0.94, 0.27, 0.27, 1))
        footer.add_widget(btn_cancel)

        self._btn_use = None
        if self._multiselect:
            self._btn_use = Factory.AppButton(text="Use Selected")
            footer.add_widget(self._btn_use)
        root.add_widget(footer)
        self.content = root

        btn_cancel.bind(on_release=lambda *_: self.dismiss())
        if self._btn_use is not None:
            self._btn_use.bind(on_release=lambda *_: self._apply())

        # Responsive columns
        self.bind(size=lambda *_: self._update_cols())
        self._update_cols()

    def on_open(self, *args):
        # Load media list in background to keep UI responsive.
        from threading import Thread

        def work():
            roots = _candidate_media_roots()
            media = _collect_media_files(roots=roots, include_videos=self._include_videos, max_items=700)
            Clock.schedule_once(lambda *_: self._set_media(media), 0)

        Thread(target=work, daemon=True).start()
        return super().on_open(*args)

    def _update_cols(self) -> None:
        try:
            w = float(self.width or Window.width or dp(360))
        except Exception:
            w = float(Window.width or dp(360))
        cols = 4 if w >= dp(720) else 3
        try:
            self._grid.cols = int(cols)
        except Exception:
            pass

    def _set_media(self, media: list[str]) -> None:
        self._media = list(media or [])
        self._grid.clear_widgets()

        if not self._media:
            self._status.text = "No photos found."
            self._grid.add_widget(Label(text="No photos found.", size_hint_y=None, height=dp(42), color=(1, 1, 1, 0.75)))
            return

        self._status.text = "Tap a photo." if not self._multiselect else "Select up to 10 photos (and optionally 1 video)."
        for fp in self._media:
            self._grid.add_widget(self._make_tile(fp))
        self._refresh_status()

    def _refresh_status(self) -> None:
        if not self._multiselect:
            return
        sel = sorted([x for x in self._selected if os.path.isfile(x)])
        images = sum(1 for x in sel if os.path.splitext(x.lower())[1] in _IMAGE_EXTS)
        videos = sum(1 for x in sel if os.path.splitext(x.lower())[1] in _VIDEO_EXTS)
        self._status.text = f"Selected: {images} photo(s)" + (f" + {videos} video" if videos else "")

    def _make_tile(self, fp: str):
        ext = os.path.splitext(str(fp).lower())[1]
        is_video = ext in _VIDEO_EXTS

        # Square-ish tiles.
        tile_h = dp(118)

        def _safe_image_tile(widget, source_path: str) -> None:
            """
            Render a thumbnail without crashing if SDL2 can't decode the file.

            Setting `Button.background_normal` to an arbitrary filesystem path can
            raise `Exception: SDL2: Unable to load image` and terminate the app.
            Using `AsyncImage` avoids hard-crashes on decode failures.
            """
            try:
                widget.background_normal = ""
                widget.background_down = ""
                widget.background_color = (1, 1, 1, 0.10)
            except Exception:
                pass

            if os.path.splitext(str(source_path).lower())[1] not in _IMAGE_EXTS:
                return
            try:
                img = Factory.AsyncImage(source=source_path, fit_mode="fill")
            except Exception:
                return

            def _sync(*_):
                try:
                    img.pos = widget.pos
                    img.size = widget.size
                except Exception:
                    return

            try:
                widget.add_widget(img)
                widget.bind(pos=_sync, size=_sync)
                _sync()
            except Exception:
                return

        if not self._multiselect:
            # Single tap selects immediately (profile image).
            btn = Button(text="", size_hint_y=None, height=tile_h)
            _safe_image_tile(btn, fp)
            if is_video:
                btn.text = "▶"
                try:
                    btn.color = (1, 1, 1, 0.92)
                except Exception:
                    pass
            btn.bind(on_release=lambda *_: self._done_single(fp))
            return btn

        tb = ToggleButton(text="", size_hint_y=None, height=tile_h)
        _safe_image_tile(tb, fp)
        if ext in _VIDEO_EXTS:
            # Video tile: no filename, just a simple icon label.
            tb.text = "▶"
            try:
                tb.color = (1, 1, 1, 0.92)
            except Exception:
                pass

        # Selection border (no filenames).
        from kivy.graphics import Color, Line

        def redraw_border(*_):
            tb.canvas.after.clear()
            if tb.state != "down":
                return
            with tb.canvas.after:
                Color(0.66, 0.33, 0.97, 0.95)
                Line(rectangle=[tb.x + dp(1), tb.y + dp(1), tb.width - dp(2), tb.height - dp(2)], width=2.0)

        tb.bind(pos=redraw_border, size=redraw_border, state=lambda *_: (self._toggle(tb, fp), redraw_border()))
        redraw_border()
        return tb

    def _toggle(self, tb: ToggleButton, fp: str) -> None:
        if tb.state == "down":
            self._selected.add(fp)
        else:
            self._selected.discard(fp)
        self._refresh_status()

    def _done_single(self, fp: str) -> None:
        if not fp or not os.path.isfile(fp):
            return
        try:
            self.dismiss()
        except Exception:
            pass
        try:
            self._on_done([fp])
        except Exception:
            return

    def _apply(self) -> None:
        selected = sorted([x for x in self._selected if os.path.isfile(x)])
        images = [x for x in selected if os.path.splitext(x.lower())[1] in _IMAGE_EXTS]
        videos = [x for x in selected if os.path.splitext(x.lower())[1] in _VIDEO_EXTS]
        if len(images) > 10:
            _popup("Error", "Maximum 10 images are allowed.")
            return
        if len(videos) > 1:
            _popup("Error", "Maximum 1 video is allowed.")
            return
        try:
            self.dismiss()
        except Exception:
            pass
        try:
            self._on_done(images + videos)
        except Exception:
            return


class SplashScreen(GestureNavigationMixin, Screen):
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


class WelcomeScreen(GestureNavigationMixin, Screen):
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

    def google_login(self) -> None:
        """
        Delegate Google Sign-In to the existing Login screen implementation.
        This keeps all auth/token storage behavior identical while placing the
        button on the Welcome screen.
        """
        if not self.manager:
            return
        try:
            login = self.manager.get_screen("login")
        except Exception:
            login = None
        if login is not None and hasattr(login, "google_login"):
            # Preserve the remembered-login preference if available.
            try:
                from frontend_app.utils.storage import get_remember_me

                setattr(login, "remember_me", bool(get_remember_me()))
            except Exception:
                pass
            try:
                login.google_login()  # type: ignore[attr-defined]
                return
            except Exception:
                pass
        # Fallback: send user to Login screen.
        try:
            self.manager.current = "login"
        except Exception:
            return


class PropertyDetailScreen(GestureNavigationMixin, Screen):
    property_id = NumericProperty(0)
    property_data = DictProperty({})

    def load_property(self, property_id: int):
        self.property_id = int(property_id)
        self.property_data = {}

        def work():
            try:
                data = api_get_property(self.property_id)
                Clock.schedule_once(lambda *_: setattr(self, "property_data", data), 0)
                # Also rebuild media grid (if KV container exists).
                Clock.schedule_once(lambda *_: self._render_media_grid(data), 0)
            except ApiError as e:
                err_msg = str(e)
                Clock.schedule_once(lambda *_dt, err_msg=err_msg: _popup("Error", err_msg), 0)

        from threading import Thread

        Thread(target=work, daemon=True).start()

    def _render_media_grid(self, data: dict[str, Any]) -> None:
        """
        Match web Property page "Photos" grid:
        - 2 columns
        - render images (AsyncImage)
        - render videos as a simple placeholder tile (video thumbnails are expensive)
        """
        try:
            container = (self.ids or {}).get("property_media_container")
        except Exception:
            container = None
        if container is None:
            return
        try:
            container.clear_widgets()
        except Exception:
            return

        items = list((data or {}).get("images") or [])
        if not items:
            container.add_widget(Label(text="No Photos", size_hint_y=None, height=dp(42), color=(1, 1, 1, 0.75)))
            return

        # Use web-like tile height (~220px). Kivy dp() scales across DPI.
        tile_h = dp(220)
        for it in items:
            it = it or {}
            url = to_api_url(str(it.get("url") or "").strip())
            ctype = str(it.get("content_type") or "").lower().strip()
            if not url:
                continue
            if ctype.startswith("video/"):
                tile = BoxLayout(size_hint_y=None, height=tile_h, padding=dp(10))
                tile.canvas.before.clear()
                container.add_widget(Label(text="[b]Video[/b]", size_hint_y=None, height=tile_h, color=(1, 1, 1, 0.78)))
            else:
                img = Factory.AsyncImage(source=url, fit_mode="fill")
                img.size_hint_y = None
                img.height = tile_h
                container.add_widget(img)

    def back(self):
        if self.manager:
            self.manager.current = "home"

    def unlock_contact(self):
        """
        Contact Unlock Flow:
        - Call the backend unlock endpoint (server enforces access rules).
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
                msg_text = f"Contact details sent to your registered email/SMS for Ad #{adv_no}{who}."
                Clock.schedule_once(lambda *_: _popup("Success", msg_text), 0)
            except ApiError as e:
                err_msg = str(e)

                def fail(*_dt):
                    _popup("Error", err_msg)

                Clock.schedule_once(fail, 0)

        from threading import Thread

        Thread(target=work, daemon=True).start()

    def share_current(self) -> None:
        p = dict(self.property_data or {})
        title_s = str(p.get("title") or "Property").strip()
        pid = int(self.property_id or 0)
        adv = str(p.get("adv_number") or p.get("ad_number") or pid or "").strip()
        meta_lines: list[str] = []
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


class MyPostsScreen(GestureNavigationMixin, Screen):
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
                                from kivy.metrics import dp

                                # Reuse HomeScreen card layout when possible, but add an Edit button.
                                home = self.manager.get_screen("home") if self.manager else None
                                for p in items:
                                    # Main card
                                    if home and hasattr(home, "feed_card"):
                                        card = home.feed_card(p)  # type: ignore[attr-defined]
                                    else:
                                        title = str((p or {}).get("title") or "Post")
                                        card = Label(text=title, size_hint_y=None, height=dp(32))

                                    wrap = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
                                    wrap.bind(minimum_height=wrap.setter("height"))
                                    wrap.add_widget(card)

                                    actions = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
                                    btn_edit = Factory.AppButton(text="Edit")
                                    actions.add_widget(btn_edit)
                                    wrap.add_widget(actions)

                                    def _edit(*_args, p=p):
                                        self.edit_post(p)

                                    btn_edit.bind(on_release=_edit)

                                    container.add_widget(wrap)
                    except Exception:
                        pass
                    self.is_loading = False

                Clock.schedule_once(done, 0)
            except ApiError as e:
                err_msg = str(e)
                Clock.schedule_once(lambda *_dt, err_msg=err_msg: _popup("Error", err_msg), 0)
                Clock.schedule_once(lambda *_: setattr(self, "is_loading", False), 0)
            except Exception as e:
                err_msg = str(e) or "Failed to load posts."
                Clock.schedule_once(lambda *_dt, err_msg=err_msg: _popup("Error", err_msg), 0)
                Clock.schedule_once(lambda *_: setattr(self, "is_loading", False), 0)

        Thread(target=work, daemon=True).start()

    # -----------------------
    # Gestures (pull-to-refresh)
    # -----------------------
    def gesture_can_refresh(self) -> bool:
        """
        Allow pull-to-refresh only when the list ScrollView is already at the top.
        """
        if self.is_loading:
            return False
        sv = None
        try:
            sv = (self.ids or {}).get("my_posts_scroll")
        except Exception:
            sv = None
        if sv is None:
            return False
        try:
            return float(getattr(sv, "scroll_y", 0.0) or 0.0) >= 0.99
        except Exception:
            return False

    def gesture_refresh(self) -> None:
        try:
            self.refresh()
        except Exception:
            return

    def back(self):
        if self.manager:
            self.manager.current = "home"

    def edit_post(self, p: dict[str, Any]) -> None:
        if not self.manager:
            return
        try:
            scr = self.manager.get_screen("owner_add_property")
            if hasattr(scr, "start_edit"):
                scr.start_edit(p)  # type: ignore[attr-defined]
            self.manager.current = "owner_add_property"
        except Exception:
            _popup("Error", "Unable to open edit screen.")


class SettingsScreen(GestureNavigationMixin, Screen):
    user_summary = StringProperty("")
    name_value = StringProperty("")
    phone_value = StringProperty("")
    email_value = StringProperty("")
    role_value = StringProperty("")
    profile_image_url = StringProperty("")
    default_profile_image = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Resolve a packaged/local placeholder image (best-effort).
        try:
            from kivy.resources import resource_find

            # Prefer a bundled Flatnow asset; avoid referencing removed QuickRent.png.
            self.default_profile_image = (
                resource_find("assets/flatnow_icon.png")
                or resource_find("assets/flatnow.png")
                or "assets/flatnow_icon.png"
            )
        except Exception:
            self.default_profile_image = "assets/flatnow_icon.png"

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
        # Avoid loading potentially stale/broken cached upload URLs before refresh.
        self.profile_image_url = ""
        self._refresh_profile_from_server()

    def _apply_user(self, u: dict[str, Any]) -> None:
        self.user_summary = f"{u.get('name') or 'User'}"
        self.name_value = str(u.get("name") or "")
        self.phone_value = str(u.get("phone") or "")
        self.email_value = str(u.get("email") or "")
        self.role_value = str(u.get("role") or "")
        self.profile_image_url = to_api_url(str(u.get("profile_image_url") or ""))

        # Keep inputs in sync if KV ids exist.
        try:
            if self.ids.get("name_input"):
                self.ids["name_input"].text = self.name_value
            if self.ids.get("phone_current"):
                self.ids["phone_current"].text = self.phone_value
            if self.ids.get("email_current"):
                self.ids["email_current"].text = self.email_value
            if self.ids.get("role_display"):
                self.ids["role_display"].text = "Owner" if self.role_value.lower() in {"owner", "admin"} else "Customer"
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
                err_msg = str(e)
                Clock.schedule_once(lambda *_dt, err_msg=err_msg: _popup("Error", err_msg), 0)

        Thread(target=work, daemon=True).start()

    def open_image_picker(self):
        """
        Use the Android system file picker (SAF) instead of scanning storage.
        This avoids permission-denied issues and UI stalls on large folders.
        """
        try:
            from plyer import filechooser  # type: ignore
        except Exception:
            filechooser = None

        def _open_picker() -> None:
            if not filechooser:
                _popup("Upload", "File picker is unavailable in this build.")
                return

            def _on_selection(selection):
                picked = ensure_local_paths(selection or [])
                if not picked:
                    return
                self.upload_profile_image(picked[0])

            try:
                filechooser.open_file(
                    on_selection=_on_selection,
                    multiple=False,
                )
            except Exception:
                _popup("Upload", "Unable to open file picker.")

        # Keep permissions best-effort (Android 13+ may not require these for SAF).
        ensure_permissions(required_media_permissions(), on_result=lambda _ok: _open_picker())

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
                err_msg = str(e)
                Clock.schedule_once(lambda *_dt, err_msg=err_msg: _popup("Error", err_msg), 0)

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
                err_msg = str(e)
                Clock.schedule_once(lambda *_dt, err_msg=err_msg: _popup("Error", err_msg), 0)

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
                err_msg = str(e)
                Clock.schedule_once(lambda *_dt, err_msg=err_msg: _popup("Error", err_msg), 0)

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
                err_msg = str(e)
                Clock.schedule_once(lambda *_dt, err_msg=err_msg: _popup("Error", err_msg), 0)

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
                err_msg = str(e)
                Clock.schedule_once(lambda *_dt, err_msg=err_msg: _popup("Error", err_msg), 0)

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
                    err_msg = str(e)
                    Clock.schedule_once(lambda *_dt, err_msg=err_msg: _popup("Error", err_msg), 0)

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

    def logout(self):
        clear_session()
        if self.manager:
            self.manager.current = "welcome"

    def go_back(self):
        if self.manager:
            self.manager.current = "home"


class SubscriptionScreen(GestureNavigationMixin, Screen):
    status_text = StringProperty("Status: loading…")
    provider_text = StringProperty("")
    expires_text = StringProperty("")
    is_loading = BooleanProperty(False)

    # Product IDs must match the Play Console subscription product IDs.
    # These defaults are safe even if not configured (purchase flow just won't find products).
    _PLAN_INSTANT = "instant_10"
    _PLAN_SMART = "smart_50"
    _PLAN_BUSINESS = "business_150"

    def on_pre_enter(self, *args):
        self.refresh_status()

    def refresh_status(self):
        if self.is_loading:
            return
        sess = get_session() or {}
        if not (sess.get("token") or ""):
            _popup("Login required", "Please login to view Subscription.")
            if self.manager:
                self.manager.current = "login"
            return
        self.is_loading = True

        from threading import Thread

        def work():
            try:
                data = api_subscription_status()
                status = str(data.get("status") or "inactive").strip() or "inactive"
                provider = str(data.get("provider") or "").strip()
                expires_at = str(data.get("expires_at") or "").strip()

                def done(*_):
                    self.status_text = f"Status: {status}"
                    self.provider_text = f"Provider: {provider}" if provider else "Provider: —"
                    self.expires_text = f"Expires: {expires_at}" if expires_at else "Expires: —"
                    self.is_loading = False

                Clock.schedule_once(done, 0)
            except ApiError as e:
                msg = str(e) or "Failed to load subscription."

                def fail(*_):
                    self.status_text = "Status: unavailable"
                    self.provider_text = ""
                    self.expires_text = ""
                    self.is_loading = False
                    _popup("Error", msg)

                Clock.schedule_once(fail, 0)

        Thread(target=work, daemon=True).start()

    def go_back(self):
        if self.manager:
            self.manager.current = "home"

    def _buy(self, product_id: str) -> None:
        try:
            from frontend_app.utils.billing import BillingUnavailable, buy_plan

            buy_plan(str(product_id))
            _popup("Subscription", "Opening Google Play purchase…")
        except BillingUnavailable as e:
            _popup("Subscription", str(e) or "Billing is unavailable on this device/build.")
        except Exception:
            _popup("Subscription", "Unable to start purchase. Please try again.")

    def buy_instant(self) -> None:
        self._buy(self._PLAN_INSTANT)

    def buy_smart(self) -> None:
        self._buy(self._PLAN_SMART)

    def buy_business(self) -> None:
        self._buy(self._PLAN_BUSINESS)


class OwnerAddPropertyScreen(GestureNavigationMixin, Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._edit_data: dict[str, Any] | None = None
        self.edit_property_id: int | None = None
        self._selected_media: list[str] = []
        self._category_items_cache: list[str] = []
        self._preferred_category: str = ""

    def start_new(self) -> None:
        """
        Open the Publish Ad screen in 'new ad' mode (not editing).
        """
        self.edit_property_id = None
        self._edit_data = None
        self._selected_media = []
        self._preferred_category = ""
        try:
            if "submit_btn" in self.ids:
                self.ids["submit_btn"].text = "Submit (goes to admin review)"
            if "title_input" in self.ids:
                self.ids["title_input"].text = ""
            if "price_input" in self.ids:
                self.ids["price_input"].text = ""
            if "contact_phone_input" in self.ids:
                self.ids["contact_phone_input"].text = ""
            if "category_spinner" in self.ids:
                self.ids["category_spinner"].text = "Select Category"
            if "media_summary" in self.ids:
                self.ids["media_summary"].text = ""
        except Exception:
            pass

    def start_edit(self, p: dict[str, Any]) -> None:
        """
        Called from MyPostsScreen to edit an existing post.
        Stores edit context and pre-fills form best-effort.
        """
        try:
            pid = int((p or {}).get("id") or 0)
        except Exception:
            pid = 0
        self.edit_property_id = pid if pid > 0 else None
        self._edit_data = dict(p or {})
        # Best-effort prefill (KV ids may not exist yet).
        self._apply_edit_prefill()

    def _apply_edit_prefill(self) -> None:
        p = self._edit_data or {}
        try:
            if "submit_btn" in self.ids:
                self.ids["submit_btn"].text = "Save Changes" if self.edit_property_id else "Submit (goes to admin review)"
            # Only auto-fill fields when editing an existing post.
            if not self.edit_property_id:
                return
            if "title_input" in self.ids:
                self.ids["title_input"].text = str(p.get("title") or "")
            if "price_input" in self.ids:
                # price_display is formatted; prefer raw int if present.
                self.ids["price_input"].text = str(p.get("price") or "")
            if "rent_sale_spinner" in self.ids:
                rs = str(p.get("rent_sale") or "").strip().title() or "Rent"
                self.ids["rent_sale_spinner"].text = rs
            if "category_spinner" in self.ids:
                cat = str(p.get("property_type") or "").strip()
                self._preferred_category = cat
                sp = self.ids["category_spinner"]
                if cat and cat in (getattr(sp, "values", None) or []):
                    sp.text = cat
                elif (sp.text or "").strip() in {"", "Select Category", "property"}:
                    sp.text = "Select Category"
            if "contact_phone_input" in self.ids:
                self.ids["contact_phone_input"].text = str(p.get("contact_phone") or p.get("phone") or "")
            if "media_summary" in self.ids:
                # Edits currently don't manage media uploads.
                self.ids["media_summary"].text = ""
        except Exception:
            return

    def category_values(self) -> list[str]:
        """
        Values for the Publish Ad category spinner (pulled from /meta/categories).
        """
        return list(getattr(self, "_category_items_cache", []) or [])

    def _load_publish_categories(self, preferred: str = "") -> None:
        """
        Load publish category list from the backend category catalog.
        """
        from threading import Thread

        def work():
            try:
                data = api_meta_categories()
                cats = data.get("categories") or []
                values: list[str] = []
                for g in cats:
                    for it in ((g or {}).get("items") or []):
                        label = str(it or "").strip()
                        if label:
                            values.append(label)

                # De-dup while keeping order
                seen: set[str] = set()
                deduped: list[str] = []
                for v in values:
                    if v in seen:
                        continue
                    seen.add(v)
                    deduped.append(v)

                def apply(*_):
                    self._category_items_cache = deduped
                    if "category_spinner" not in self.ids:
                        return
                    sp = self.ids["category_spinner"]
                    sp.values = self.category_values()

                    pref = (preferred or self._preferred_category or "").strip()
                    if pref and pref in (sp.values or []):
                        sp.text = pref
                        return

                    # Pick a sensible default when empty.
                    if (sp.text or "").strip() in {"", "Select Category", "property"}:
                        pick = next((x for x in (sp.values or []) if "apartment" in str(x).lower()), None) or ((sp.values or [None])[0])
                        sp.text = pick or "Select Category"

                Clock.schedule_once(apply, 0)
            except Exception:
                return

        Thread(target=work, daemon=True).start()

    def on_pre_enter(self, *args):
        # Load location dropdowns from backend (and default to profile state/district if present).
        u = get_user() or {}
        p = self._edit_data or {}
        preferred_state = str(p.get("state") or u.get("state") or "").strip()
        preferred_district = str(p.get("district") or u.get("district") or "").strip()
        preferred_area = str(p.get("area") or "").strip()
        self._apply_edit_prefill()
        self._load_publish_categories(str(p.get("property_type") or "").strip())

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
                    if preferred_area:
                        Clock.schedule_once(lambda *_: self._apply_preferred_area(preferred_area), 0.35)

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

    def _apply_preferred_area(self, preferred_area: str):
        try:
            if "area_spinner" not in self.ids:
                return
            sp = self.ids["area_spinner"]
            if preferred_area and preferred_area in (sp.values or []):
                sp.text = preferred_area
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
        Pick up to 10 images + 1 video to upload with the ad (Android file picker).
        """
        try:
            from plyer import filechooser  # type: ignore
        except Exception:
            filechooser = None

        def _open_picker() -> None:
            if not filechooser:
                _popup("Upload", "File picker is unavailable in this build.")
                return

            def _on_selection(selection):
                picked = ensure_local_paths(selection or [])
                # Treat unknown extensions as images (SAF display names typically include extensions).
                videos = [p for p in picked if is_video_path(p)]
                images = [p for p in picked if p not in videos]
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

            try:
                filechooser.open_file(
                    on_selection=_on_selection,
                    multiple=True,
                )
            except Exception:
                _popup("Upload", "Unable to open file picker.")

        ensure_permissions(required_media_permissions(), on_result=lambda _ok: _open_picker())

    def submit_listing(self):
        """
        Create the ad (goes to admin review).
        Location/Address are removed from UI as requested.
        """
        title = (self.ids.get("title_input").text or "").strip() if self.ids.get("title_input") else ""
        state = (self.ids.get("state_spinner").text or "").strip() if self.ids.get("state_spinner") else ""
        district = (self.ids.get("district_spinner").text or "").strip() if self.ids.get("district_spinner") else ""
        area = (self.ids.get("area_spinner").text or "").strip() if self.ids.get("area_spinner") else ""
        category = (self.ids.get("category_spinner").text or "").strip() if self.ids.get("category_spinner") else ""
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
        if not category or category in {"Select Category"}:
            _popup("Error", "Please select category.")
            return

        try:
            price = int(price_text) if price_text else 0
        except Exception:
            _popup("Error", "Enter a valid price.")
            return

        from threading import Thread
        # api_owner_create_property/api_owner_update_property imported at module level

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
                if self.edit_property_id:
                    res = api_owner_update_property(property_id=int(self.edit_property_id), payload=payload)
                    pid = self.edit_property_id
                    status = ((res.get("property") or {}).get("status") or "updated").strip() if isinstance(res, dict) else "updated"
                else:
                    res = api_owner_create_property(payload=payload)
                    pid = res.get("id")
                    status = res.get("status") or "pending"

                # Upload selected media (best-effort).
                selected = list(getattr(self, "_selected_media", []) or [])
                if (not self.edit_property_id) and pid and selected:
                    for i, fp in enumerate(selected):
                        api_upload_property_media(property_id=int(pid), file_path=str(fp), sort_order=i)

                def done(*_):
                    if self.edit_property_id:
                        msg = f"Ad updated (#{pid})"
                    else:
                        msg = f"Ad created (#{pid}) • status: {status}"
                    if selected and (not self.edit_property_id):
                        msg += f"\nUploaded {len(selected)} file(s)."
                    _popup("Saved", msg)
                    if self.manager:
                        # Refresh lists so edits reflect everywhere.
                        try:
                            home = self.manager.get_screen("home")
                            if hasattr(home, "refresh"):
                                home.refresh()  # type: ignore[attr-defined]
                        except Exception:
                            pass
                        try:
                            mp = self.manager.get_screen("my_posts")
                            if hasattr(mp, "refresh"):
                                mp.refresh()  # type: ignore[attr-defined]
                        except Exception:
                            pass
                        # After save, show the user's posts list (no dashboard screen).
                        self.manager.current = "my_posts"
                        # Exit edit mode after save.
                        self.edit_property_id = None
                        self._edit_data = None

                Clock.schedule_once(done, 0)
            except ApiError as e:
                err_msg = str(e)
                Clock.schedule_once(lambda *_dt, err_msg=err_msg: _popup("Error", err_msg), 0)

        def _maybe_with_location(ok: bool) -> None:
            # For edits, don't force location permission / GPS capture.
            if self.edit_property_id:
                def work():
                    _start_submit(None, None)
                Thread(target=work, daemon=True).start()
                return

            loc = get_last_known_location() if ok else None
            gps_lat, gps_lng = (loc[0], loc[1]) if loc else (None, None)

            def work():
                _start_submit(gps_lat, gps_lng)

            Thread(target=work, daemon=True).start()

        # Request location permission at runtime (best-effort). Submission continues even if denied.
        ensure_permissions(required_location_permissions(), on_result=_maybe_with_location)

    def go_back(self):
        if self.manager:
            # Back should return to My Posts when editing, otherwise Home.
            self.manager.current = "my_posts" if self.edit_property_id else "home"


