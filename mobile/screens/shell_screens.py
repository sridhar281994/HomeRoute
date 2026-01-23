from __future__ import annotations

import os
from typing import Any

from kivy.clock import Clock
from kivy.factory import Factory
from kivy.metrics import dp
from kivy.properties import BooleanProperty, DictProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.label import Label
from kivy.uix.popup import Popup
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


class SplashScreen(GestureNavigationMixin, Screen):
    def on_enter(self, *args):
        # Enable gesture capture even when child widgets consume touches.
        try:
            self.gesture_bind_window()
        except Exception:
            pass
        # Small delay then continue to Welcome or Home (if already logged in).
        Clock.schedule_once(lambda _dt: self._go_next(), 0.9)

    def on_leave(self, *args):
        try:
            self.gesture_unbind_window()
        except Exception:
            pass
        return super().on_leave(*args)

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
        try:
            self.gesture_bind_window()
        except Exception:
            pass
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

    def on_leave(self, *args):
        try:
            self.gesture_unbind_window()
        except Exception:
            pass
        return super().on_leave(*args)

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

    def on_pre_enter(self, *args):
        try:
            self.gesture_bind_window()
        except Exception:
            pass

    def on_leave(self, *args):
        try:
            self.gesture_unbind_window()
        except Exception:
            pass
        return super().on_leave(*args)

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
                img = Factory.AsyncImage(source=url, allow_stretch=True, keep_ratio=False)
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
        try:
            self.gesture_bind_window()
        except Exception:
            pass
        self.refresh()

    def on_leave(self, *args):
        try:
            self.gesture_unbind_window()
        except Exception:
            pass
        return super().on_leave(*args)

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

            self.default_profile_image = resource_find("assets/flatnow_all.png") or "assets/flatnow_all.png"
        except Exception:
            self.default_profile_image = "assets/flatnow_all.png"

    def on_pre_enter(self, *args):
        try:
            self.gesture_bind_window()
        except Exception:
            pass
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

    def on_leave(self, *args):
        try:
            self.gesture_unbind_window()
        except Exception:
            pass
        return super().on_leave(*args)

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
        def _open_picker() -> None:
            # Android: prefer native SAF picker (no folder scanning).
            try:
                from kivy.utils import platform as _platform
            except Exception:
                _platform = ""

            if _platform == "android":
                try:
                    from plyer import filechooser  # type: ignore
                except Exception:
                    filechooser = None

                if filechooser is None:
                    _popup("Gallery picker unavailable", "Please install or enable a gallery app to choose photos.")
                    return

                def _on_sel(selection):
                    try:
                        paths = ensure_local_paths(selection or [])
                        img = next((p for p in paths if is_image_path(p)), "")
                        if img:
                            self.upload_profile_image(img)
                    except Exception:
                        return

                try:
                    filechooser.open_file(on_selection=_on_sel, multiple=False)
                    return
                except Exception:
                    _popup("Gallery picker unavailable", "Unable to open Android gallery picker.")
                    return

            from kivy.uix.behaviors import ButtonBehavior
            from kivy.uix.floatlayout import FloatLayout
            from kivy.uix.gridlayout import GridLayout
            from kivy.uix.image import AsyncImage
            from kivy.uix.scrollview import ScrollView

            def _collect_roots() -> list[str]:
                roots: list[str] = []
                primary = _default_media_dir()
                if primary:
                    roots.append(primary)
                for extra in [
                    "/storage/emulated/0/DCIM",
                    "/storage/emulated/0/Pictures",
                    "/sdcard/DCIM",
                    "/sdcard/Pictures",
                ]:
                    if extra not in roots and os.path.isdir(extra):
                        roots.append(extra)
                return roots

            def _list_images() -> list[str]:
                exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
                seen: set[str] = set()
                out: list[str] = []
                for root in _collect_roots():
                    for dirpath, _dirs, files in os.walk(root):
                        for name in files:
                            ext = os.path.splitext(name.lower())[1]
                            if ext not in exts:
                                continue
                            fp = os.path.join(dirpath, name)
                            if fp in seen:
                                continue
                            seen.add(fp)
                            out.append(fp)
                            if len(out) >= 400:
                                break
                        if len(out) >= 400:
                            break
                    if len(out) >= 400:
                        break

                def _mtime(path: str) -> float:
                    try:
                        return os.path.getmtime(path)
                    except Exception:
                        return 0.0

                out.sort(key=_mtime, reverse=True)
                return out

            class _ImageTile(ButtonBehavior, FloatLayout):
                def __init__(self, file_path: str, **kwargs):
                    super().__init__(**kwargs)
                    self.file_path = file_path
                    img = AsyncImage(source=file_path, allow_stretch=True, keep_ratio=False)
                    self.add_widget(img)

            popup = Popup(title="Choose Profile Image", size_hint=(0.94, 0.94), auto_dismiss=False)

            grid = GridLayout(cols=3, spacing=dp(8), size_hint_y=None)
            grid.bind(minimum_height=grid.setter("height"))
            scroll = ScrollView(do_scroll_x=False, bar_width=dp(6))
            scroll.add_widget(grid)

            def select_image(fp: str) -> None:
                try:
                    popup.dismiss()
                    self.upload_profile_image(fp)
                except Exception:
                    popup.dismiss()

            images = _list_images()
            for fp in images:
                tile = _ImageTile(fp, size_hint_y=None, height=dp(110))
                tile.bind(on_release=lambda _btn, p=fp: select_image(p))
                grid.add_widget(tile)

            if not images:
                grid.add_widget(Label(text="No photos found.", size_hint_y=None, height=dp(32), color=(1, 1, 1, 0.75)))

            buttons = BoxLayout(size_hint_y=None, height=dp(54), spacing=dp(10), padding=[dp(10), dp(10)])
            btn_cancel = Factory.AppButton(text="Cancel", color=(0.94, 0.27, 0.27, 1))
            buttons.add_widget(btn_cancel)

            root = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))
            root.add_widget(Label(text="Tap an image to upload immediately."))
            root.add_widget(scroll)
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

    def on_pre_enter(self, *args):
        try:
            self.gesture_bind_window()
        except Exception:
            pass
        self.refresh_status()

    def on_leave(self, *args):
        try:
            self.gesture_unbind_window()
        except Exception:
            pass
        return super().on_leave(*args)

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
        try:
            self.gesture_bind_window()
        except Exception:
            pass
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

    def on_leave(self, *args):
        try:
            self.gesture_unbind_window()
        except Exception:
            pass
        return super().on_leave(*args)

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
        Pick up to 10 images + 1 video to upload with the ad.
        """
        def _open_picker() -> None:
            # Android: prefer native SAF picker (no folder scanning).
            try:
                from kivy.utils import platform as _platform
            except Exception:
                _platform = ""

            if _platform == "android":
                try:
                    from plyer import filechooser  # type: ignore
                except Exception:
                    filechooser = None

                if filechooser is None:
                    _popup("Gallery picker unavailable", "Please install or enable a gallery app to choose media.")
                    return

                def _on_sel(selection):
                    try:
                        paths = ensure_local_paths(selection or [])
                        media = [p for p in paths if is_image_path(p) or is_video_path(p)]
                        self._selected_media = list(media)
                        images = [x for x in self._selected_media if is_image_path(x)]
                        videos = [x for x in self._selected_media if is_video_path(x)]
                        if "media_summary" in self.ids:
                            parts = []
                            if images:
                                parts.append(f"{len(images)} image(s)")
                            if videos:
                                parts.append(f"{len(videos)} video(s)")
                            self.ids["media_summary"].text = ("Selected: " + " + ".join(parts)) if parts else ""
                    except Exception:
                        return

                try:
                    filechooser.open_file(on_selection=_on_sel, multiple=True)
                    return
                except Exception:
                    _popup("Gallery picker unavailable", "Unable to open Android gallery picker.")
                    return

            """
            Custom media picker:
            - Folder navigation (list)
            - On open, show folder contents as a scrollable preview grid (thumbnails for photos)
            - Multi-select with validation (max 10 images + 1 video)
            """

            def _is_image(fp: str) -> bool:
                ext = os.path.splitext(fp.lower())[1]
                return ext in {".png", ".jpg", ".jpeg", ".webp", ".gif"}

            def _is_video(fp: str) -> bool:
                ext = os.path.splitext(fp.lower())[1]
                return ext in {".mp4", ".mov", ".m4v", ".avi", ".mkv"}

            class _MediaPickerPopup(Popup):
                def __init__(self, **kwargs):
                    super().__init__(**kwargs)
                    self.title = "Choose Media (max 10 images + 1 video)"
                    self.size_hint = (0.94, 0.94)
                    self.auto_dismiss = False

                    self._mode = "folders"  # folders|grid
                    self._path = os.path.abspath(_default_media_dir())
                    self._selected: set[str] = set()

                    root = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))

                    # Header (path + actions)
                    header = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
                    btn_up = Factory.AppButton(text="Up", size_hint_x=None, width=dp(90))
                    path_label = os.path.basename(self._path) or "Photos"
                    self._path_lbl = Label(text=path_label, halign="left", valign="middle", color=(1, 1, 1, 0.78))
                    self._path_lbl.text_size = (0, None)
                    header.add_widget(btn_up)
                    header.add_widget(self._path_lbl)
                    root.add_widget(header)

                    # Folder list view
                    self._chooser = FileChooserListView(path=self._path, filters=[], multiselect=False, dirselect=True)

                    # Grid view
                    from kivy.uix.scrollview import ScrollView
                    from kivy.uix.togglebutton import ToggleButton
                    from kivy.uix.image import AsyncImage
                    from kivy.uix.gridlayout import GridLayout

                    self._grid_scroll = ScrollView(do_scroll_x=False, bar_width=dp(6))
                    self._grid = GridLayout(cols=3, spacing=dp(8), size_hint_y=None)
                    self._grid.bind(minimum_height=self._grid.setter("height"))
                    self._grid_scroll.add_widget(self._grid)

                    # Footer buttons
                    footer = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(10))
                    btn_cancel = Factory.AppButton(text="Cancel", color=(0.94, 0.27, 0.27, 1))
                    btn_open = Factory.AppButton(text="Folders")
                    btn_use = Factory.AppButton(text="Use Selected")
                    footer.add_widget(btn_cancel)
                    footer.add_widget(btn_open)
                    footer.add_widget(btn_use)
                    root.add_widget(Label(text="Select up to 10 images and optionally 1 video.", size_hint_y=None, height=dp(22), color=(1, 1, 1, 0.78)))

                    self._body = BoxLayout()
                    root.add_widget(self._body)
                    root.add_widget(footer)
                    self.content = root

                    def _set_path(new_path: str) -> None:
                        p = os.path.abspath(str(new_path or "").strip() or self._path)
                        if not os.path.isdir(p):
                            return
                        self._path = p
                        try:
                            self._path_lbl.text = os.path.basename(p) or "Photos"
                        except Exception:
                            pass
                        try:
                            self._chooser.path = p
                        except Exception:
                            pass

                    def _go_up(*_):
                        parent = os.path.dirname(self._path.rstrip(os.sep))
                        if parent and parent != self._path:
                            _set_path(parent)
                            if self._mode == "grid":
                                _show_grid()

                    def _list_dir(p: str) -> tuple[list[str], list[str]]:
                        """
                        Returns (dirs, media_files) within p.
                        """
                        try:
                            items = [os.path.join(p, x) for x in os.listdir(p)]
                        except Exception:
                            return ([], [])
                        dirs = []
                        media = []
                        for fp in items:
                            try:
                                if os.path.isdir(fp):
                                    dirs.append(fp)
                                elif os.path.isfile(fp) and (_is_image(fp) or _is_video(fp)):
                                    media.append(fp)
                            except Exception:
                                continue
                        dirs.sort(key=lambda x: os.path.basename(x).lower())
                        media.sort(key=lambda x: os.path.basename(x).lower())
                        return (dirs, media)

                    def _toggle_select(fp: str, active: bool) -> None:
                        if active:
                            self._selected.add(fp)
                        else:
                            self._selected.discard(fp)

                    def _render_tile_dir(fp: str) -> None:
                        name = os.path.basename(fp.rstrip(os.sep)) or fp
                        tile = Factory.AppButton(text=f"[b]{name}[/b]\n[small](Folder)[/small]")
                        tile.size_hint_y = None
                        tile.height = dp(110)
                        tile.bind(on_release=lambda *_: (_set_path(fp), _show_grid()))
                        self._grid.add_widget(tile)

                    def _render_tile_media(fp: str) -> None:
                        # ToggleButton lets the user tap to select/deselect.
                        wrap = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(150), spacing=dp(6))
                        if _is_image(fp):
                            img = AsyncImage(source=fp, allow_stretch=True, keep_ratio=False)
                            img.size_hint_y = None
                            img.height = dp(110)
                            wrap.add_widget(img)
                        else:
                            # Video: simple placeholder tile (thumbnail extraction is expensive).
                            wrap.add_widget(Label(text="[b]Video[/b]", size_hint_y=None, height=dp(110), color=(1, 1, 1, 0.78)))

                        tb = ToggleButton(text="", size_hint_y=None, height=dp(32))
                        tb.state = "down" if fp in self._selected else "normal"

                        def _sync_label(btn):
                            btn.text = "✓" if btn.state == "down" else ""

                        def _on_state(btn, value):
                            _toggle_select(fp, value == "down")
                            _sync_label(btn)

                        _sync_label(tb)
                        tb.bind(state=_on_state)
                        wrap.add_widget(tb)
                        self._grid.add_widget(wrap)

                    def _show_folders(*_) -> None:
                        self._mode = "folders"
                        self._body.clear_widgets()
                        self._body.add_widget(self._chooser)
                        btn_open.disabled = False
                        btn_open.text = "Open folder"
                        btn_use.disabled = True

                    def _show_grid(*_) -> None:
                        self._mode = "grid"
                        self._body.clear_widgets()
                        self._body.add_widget(self._grid_scroll)
                        # Keep a way to jump back to folder list if user prefers.
                        btn_open.disabled = False
                        btn_open.text = "Folders"
                        btn_use.disabled = False

                        # rebuild grid
                        self._grid.clear_widgets()
                        dirs, media = _list_dir(self._path)
                        # Dirs first
                        for d in dirs[:120]:
                            _render_tile_dir(d)
                        # Then media
                        for fp in media[:400]:
                            _render_tile_media(fp)
                        if not dirs and not media:
                            self._grid.add_widget(Label(text="No photos/videos found in this folder.", size_hint_y=None, height=dp(42), color=(1, 1, 1, 0.75)))

                    def _open_folder(*_):
                        # Choose folder from list view; fallback to current path.
                        try:
                            sel = list(self._chooser.selection or [])
                            if sel:
                                _set_path(sel[0])
                        except Exception:
                            pass
                        _show_grid()

                    def _toggle_folders_or_open(*_):
                        # In grid mode: show folder list. In folder mode: open selected folder.
                        if self._mode == "grid":
                            _show_folders()
                        else:
                            _open_folder()

                    def _apply(*_):
                        selected = sorted([x for x in self._selected if os.path.isfile(x)])
                        images = [x for x in selected if _is_image(x)]
                        videos = [x for x in selected if _is_video(x)]
                        if len(images) > 10:
                            _popup("Error", "Maximum 10 images are allowed.")
                            return
                        if len(videos) > 1:
                            _popup("Error", "Maximum 1 video is allowed.")
                            return
                        self.dismiss()
                        self._on_done(images + videos)

                    btn_up.bind(on_release=_go_up)
                    btn_cancel.bind(on_release=lambda *_: self.dismiss())
                    btn_open.bind(on_release=_toggle_folders_or_open)
                    btn_use.bind(on_release=_apply)

                    # Expose selection to caller.
                    self._on_done = lambda _sel: None

                    # UX: open straight into a scrollable preview grid (folders as tiles),
                    # so users immediately see photos/videos instead of a folder list.
                    _show_grid()

            popup = _MediaPickerPopup()

            def _done(selected: list[str]) -> None:
                try:
                    self._selected_media = list(selected or [])
                    images = [x for x in self._selected_media if _is_image(x)]
                    videos = [x for x in self._selected_media if _is_video(x)]
                    if "media_summary" in self.ids:
                        parts: list[str] = []
                        if images:
                            parts.append(f"{len(images)} image(s)")
                        if videos:
                            parts.append("1 video")
                        self.ids["media_summary"].text = ("Selected: " + " + ".join(parts)) if parts else ""
                except Exception:
                    pass

            popup._on_done = _done  # type: ignore[attr-defined]
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


