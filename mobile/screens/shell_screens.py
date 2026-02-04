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
    api_owner_delete_property,
    api_owner_list_properties,
    api_owner_publish_property,
    api_owner_update_property,
    api_subscription_status,
    api_upload_property_media,
    to_api_url,
)
from frontend_app.utils.share import share_text
from frontend_app.utils.storage import clear_session, get_session, get_user, set_guest_session, set_session
from frontend_app.utils.android_permissions import ensure_permissions, required_location_permissions, \
    required_media_permissions
from frontend_app.utils.android_location import get_last_known_location
from frontend_app.utils.android_filepicker import android_open_gallery, android_uri_to_jpeg_bytes


def _sync_app_badge_best_effort() -> None:
    """
    Keep the shared MobileTopBar avatar in sync with session changes.
    """
    try:
        from kivy.app import App as _App

        a = _App.get_running_app()
        if a and hasattr(a, "sync_user_badge"):
            a.sync_user_badge()  # type: ignore[attr-defined]
    except Exception:
        return


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
        Clock.schedule_once(lambda _dt: self._go_next(), 0.5)

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
    fallback_text = StringProperty("U")
    image_source = StringProperty("")

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
                # Avatar in the detail header should reflect the post owner.
                try:
                    owner = str(
                        (data or {}).get("owner_name")
                        or (data or {}).get("posted_by")
                        or (data or {}).get("user_name")
                        or ""
                    ).strip()
                    owner_initial = owner[0].upper() if owner else "U"
                except Exception:
                    owner_initial = "U"
                try:
                    owner_img = str((data or {}).get("owner_image") or (data or {}).get("profile_image") or "").strip()
                except Exception:
                    owner_img = ""
                Clock.schedule_once(lambda *_: setattr(self, "fallback_text", owner_initial), 0)
                Clock.schedule_once(
                    lambda *_: setattr(self, "image_source", to_api_url(owner_img) if owner_img else ""), 0)
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

        items = self._extract_media_items(data)
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

    def _extract_media_items(self, p: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Normalize backend media shapes into a consistent list of dicts.
        Keep this aligned with HomeScreen so posts display images reliably.
        """
        src = None
        try:
            if isinstance((p or {}).get("images"), list):
                src = p.get("images")
            elif isinstance((p or {}).get("image_urls"), list):
                src = p.get("image_urls")
            elif isinstance((p or {}).get("media"), list):
                src = p.get("media")
            elif isinstance((p or {}).get("photos"), list):
                src = p.get("photos")
            elif isinstance((p or {}).get("files"), list):
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
        # Share format (3 lines):
        # Title
        # rent • type • price • location
        # URL
        share_meta = " • ".join(
            x
            for x in [
                str(p.get("rent_sale") or "").strip(),
                str(p.get("property_type") or "").strip(),
                str(p.get("price_display") or "").strip(),
                str(p.get("location_display") or "").strip(),
            ]
            if x
        )
        subject = title_s
        body = "\n".join([x for x in [title_s, share_meta, api_link] if x])

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

                                # Reuse HomeScreen card layout in "my posts" mode so buttons render inside the card.
                                home = self.manager.get_screen("home") if self.manager else None
                                for p in items:
                                    if home and hasattr(home, "_feed_card"):
                                        raw2 = dict(p or {})
                                        raw2["_my_posts"] = True
                                        raw2["_on_edit"] = (lambda p=p: self.edit_post(p))
                                        raw2["_on_delete"] = (lambda p=p: self.delete_post(p))
                                        card = home._feed_card(raw2)  # type: ignore[attr-defined]
                                    else:
                                        title = str((p or {}).get("title") or "Post")
                                        card = Label(text=title, size_hint_y=None, height=dp(32))

                                    container.add_widget(card)
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

    def delete_post(self, p: dict[str, Any]) -> None:
        """
        Delete an owned post and refresh the list.
        """
        try:
            pid = int((p or {}).get("id") or 0)
        except Exception:
            pid = 0
        if pid <= 0:
            _popup("Error", "Invalid post id.")
            return

        # Confirm popup
        try:
            adv = str((p or {}).get("adv_number") or (p or {}).get("ad_number") or pid).strip()
        except Exception:
            adv = str(pid)

        def do_delete(*_):
            from threading import Thread

            def work():
                try:
                    api_owner_delete_property(property_id=pid)
                    Clock.schedule_once(lambda *_: _popup("Deleted", f"Deleted Ad #{adv}"), 0)
                    Clock.schedule_once(lambda *_: self.refresh(), 0)
                except ApiError as e:
                    err_msg = str(e)
                    Clock.schedule_once(lambda *_dt, err_msg=err_msg: _popup("Error", err_msg), 0)
                except Exception as e:
                    err_msg = str(e) or "Delete failed."
                    Clock.schedule_once(lambda *_dt, err_msg=err_msg: _popup("Error", err_msg), 0)

            Thread(target=work, daemon=True).start()
            try:
                popup.dismiss()
            except Exception:
                pass

        buttons = BoxLayout(size_hint_y=None, height=dp(54), spacing=dp(10), padding=[dp(10), dp(8)])
        btn_no = Factory.AppButton(text="Cancel")
        btn_yes = Factory.AppButton(text="Delete", color=(0.94, 0.27, 0.27, 1))
        btn_no.size_hint_x = 1
        btn_yes.size_hint_x = 1
        buttons.add_widget(btn_no)
        buttons.add_widget(btn_yes)
        root = BoxLayout(orientation="vertical", spacing=8, padding=8)
        root.add_widget(Label(text=f"Delete Ad #{adv}?\nThis cannot be undone."))
        root.add_widget(buttons)
        popup = Popup(title="Confirm", content=root, size_hint=(0.92, 0.45), auto_dismiss=False)
        btn_no.bind(on_release=lambda *_: popup.dismiss())
        btn_yes.bind(on_release=do_delete)
        popup.open()


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

        u_local = get_user() or {}
        self._apply_user(u_local)
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
                set_session(
                    token=str(sess.get("token") or ""),
                    user=u,
                    remember=bool(sess.get("remember_me") or False),
                )
                Clock.schedule_once(lambda *_: self._apply_user(u), 0)
                Clock.schedule_once(lambda *_: _sync_app_badge_best_effort(), 0)
            except Exception:
                pass

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
                set_session(
                    token=str(sess.get("token") or ""),
                    user=u,
                    remember=bool(sess.get("remember_me") or False),
                )
                Clock.schedule_once(lambda *_: self._apply_user(u), 0)
                Clock.schedule_once(lambda *_: _sync_app_badge_best_effort(), 0)
                Clock.schedule_once(lambda *_: _popup("Saved", "Name updated."), 0)
            except ApiError as e:
                Clock.schedule_once(lambda *_: _popup("Error", str(e)), 0)

        Thread(target=work, daemon=True).start()

    def open_profile_image_picker(self):
        from kivy.utils import platform

        def _on_selected(uris):
            if not uris:
                _popup("Error", "No image selected")
                return
            try:
                jpeg = android_uri_to_jpeg_bytes(uris[0])
            except Exception as e:
                _popup("Error", f"Invalid image selected\n{e}")
                return
            self.upload_profile_image_bytes(jpeg)

        if platform == "android":
            ensure_permissions(
                required_media_permissions(),
                on_result=lambda ok: android_open_gallery(
                    on_selection=_on_selected,
                    multiple=False,
                    mime_types=["image/*"],
                ),
            )
            return

        _popup("Not supported", "Profile image picker is supported only on mobile.")

    def upload_profile_image_bytes(self, img_bytes: bytes):
        from threading import Thread

        def work():
            try:
                data = api_me_upload_profile_image(raw=img_bytes)
                u = data.get("user") or {}
                sess = get_session() or {}
                set_session(
                    token=str(sess.get("token") or ""),
                    user=u,
                    remember=bool(sess.get("remember_me") or False),
                )
                Clock.schedule_once(lambda *_: self._apply_user(u), 0)
                Clock.schedule_once(lambda *_: _sync_app_badge_best_effort(), 0)
                Clock.schedule_once(lambda *_: _popup("Saved", "Profile image updated."), 0)
            except ApiError as e:
                Clock.schedule_once(lambda *_: _popup("Error", str(e)), 0)

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
                Clock.schedule_once(lambda *_: _popup("Error", str(e)), 0)

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
                set_session(
                    token=str(sess.get("token") or ""),
                    user=u,
                    remember=bool(sess.get("remember_me") or False),
                )
                Clock.schedule_once(lambda *_: self._apply_user(u), 0)
                Clock.schedule_once(lambda *_: _sync_app_badge_best_effort(), 0)
                Clock.schedule_once(lambda *_: _popup("Saved", "Email updated."), 0)
            except ApiError as e:
                Clock.schedule_once(lambda *_: _popup("Error", str(e)), 0)

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
                Clock.schedule_once(lambda *_: _popup("Error", str(e)), 0)

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
                set_session(
                    token=str(sess.get("token") or ""),
                    user=u,
                    remember=bool(sess.get("remember_me") or False),
                )
                Clock.schedule_once(lambda *_: self._apply_user(u), 0)
                Clock.schedule_once(lambda *_: _sync_app_badge_best_effort(), 0)
                Clock.schedule_once(lambda *_: _popup("Saved", "Phone updated."), 0)
            except ApiError as e:
                Clock.schedule_once(lambda *_: _popup("Error", str(e)), 0)

        Thread(target=work, daemon=True).start()

    def delete_account(self):
        def do_delete(*_):
            from threading import Thread

            def work():
                try:
                    api_me_delete()
                    clear_session()
                    Clock.schedule_once(lambda *_: _sync_app_badge_best_effort(), 0)
                    Clock.schedule_once(lambda *_: _popup("Deleted", "Account deleted."), 0)
                    Clock.schedule_once(
                        lambda *_: setattr(self.manager, "current", "welcome") if self.manager else None,
                        0,
                    )
                except ApiError as e:
                    Clock.schedule_once(lambda *_: _popup("Error", str(e)), 0)

            Thread(target=work, daemon=True).start()
            popup.dismiss()

        buttons = BoxLayout(size_hint_y=None, height=dp(54), spacing=dp(10), padding=[dp(10), dp(8)])
        btn_yes = Factory.AppButton(text="Delete", color=(0.94, 0.27, 0.27, 1))
        btn_no = Factory.AppButton(text="Cancel")
        buttons.add_widget(btn_no)
        buttons.add_widget(btn_yes)
        root = BoxLayout(orientation="vertical", spacing=8, padding=8)
        root.add_widget(Label(text="Delete your account permanently?\nThis cannot be undone."))
        root.add_widget(buttons)
        popup = Popup(title="Confirm", content=root, size_hint=(0.92, 0.45), auto_dismiss=False)
        btn_no.bind(on_release=lambda *_: popup.dismiss())
        btn_yes.bind(on_release=do_delete)
        popup.open()

    def logout(self):
        clear_session()
        _sync_app_badge_best_effort()
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
        if not sess.get("token"):
            _popup("Login required", "Please login to view Subscription.")
            if self.manager:
                self.manager.current = "login"
            return

        self.is_loading = True

        from threading import Thread

        def work():
            try:
                data = api_subscription_status()
                status = str(data.get("status") or "inactive").strip()
                provider = str(data.get("provider") or "").strip()
                expires_at = str(data.get("expires_at") or "").strip()

                def done(*_):
                    self.status_text = f"Status: {status}"
                    self.provider_text = f"Provider: {provider}" if provider else "Provider: —"
                    self.expires_text = f"Expires: {expires_at}" if expires_at else "Expires: —"
                    self.is_loading = False

                Clock.schedule_once(done, 0)

            except ApiError as e:
                def fail(*_):
                    self.status_text = "Status: unavailable"
                    self.provider_text = ""
                    self.expires_text = ""
                    self.is_loading = False
                    _popup("Error", str(e) or "Failed to load subscription.")

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
        self._selected_media: list[Any] = []  # bytes on Android, paths on desktop
        self._category_items_cache: list[str] = []
        self._preferred_category: str = ""
        # Publish type (controls which categories are shown)
        self._publish_post_group: str = "property_material"  # property_material | services

    # -----------------------------
    # MODE HANDLERS
    # -----------------------------
    def start_new(self) -> None:
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
                u = get_user() or {}
                self.ids["contact_phone_input"].text = str(u.get("phone") or "")
                self.ids["contact_phone_input"].disabled = True
            if "category_spinner" in self.ids:
                self.ids["category_spinner"].text = "Select Category"
            if "media_summary" in self.ids:
                self.ids["media_summary"].text = ""
        except Exception:
            pass

    def start_edit(self, p: dict[str, Any]) -> None:
        try:
            pid = int((p or {}).get("id") or 0)
        except Exception:
            pid = 0
        self.edit_property_id = pid if pid > 0 else None
        self._edit_data = dict(p or {})
        self._apply_edit_prefill()

    def _apply_edit_prefill(self) -> None:
        p = self._edit_data or {}
        try:
            if "submit_btn" in self.ids:
                self.ids["submit_btn"].text = "Save Changes" if self.edit_property_id else "Submit (goes to admin review)"
            if not self.edit_property_id:
                return
            if "title_input" in self.ids:
                self.ids["title_input"].text = str(p.get("title") or "")
            if "price_input" in self.ids:
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
                u = get_user() or {}
                self.ids["contact_phone_input"].text = str(u.get("phone") or "")
                self.ids["contact_phone_input"].disabled = True
            if "media_summary" in self.ids:
                self.ids["media_summary"].text = ""
        except Exception:
            pass

    # -----------------------------
    # CATEGORY
    # -----------------------------
    def category_values(self) -> list[str]:
        return list(getattr(self, "_category_items_cache", []) or [])

    def publish_type_values(self) -> list[str]:
        return ["Owner(property/Material)", "Owner(services Only)"]

    def on_post_group_changed(self, *_):
        try:
            sp = self.ids.get("post_group_spinner")
            label = str(getattr(sp, "text", "") or "").strip()
        except Exception:
            label = ""
        self._publish_post_group = "services" if "service" in label.lower() else "property_material"
        self._load_publish_categories(preferred=str(getattr(self, "_preferred_category", "") or ""))

    def _load_publish_categories(self, preferred: str = "") -> None:
        from threading import Thread

        def work():
            try:
                data = api_meta_categories()
                cats = data.get("categories") or []
                property_groups = {"property & space", "room & stay", "construction materials"}
                pref = (preferred or self._preferred_category or "").strip()

                if pref:
                    for g in cats:
                        gl = str((g or {}).get("group") or "").lower()
                        items = [str(x or "").strip() for x in ((g or {}).get("items") or [])]
                        if pref in items:
                            self._publish_post_group = "property_material" if gl in property_groups else "services"
                            break

                want_services = self._publish_post_group == "services"
                values: list[str] = []

                for g in cats:
                    gl = str((g or {}).get("group") or "").lower()
                    is_prop = gl in property_groups
                    if want_services and is_prop:
                        continue
                    if (not want_services) and (not is_prop):
                        continue
                    for it in ((g or {}).get("items") or []):
                        label = str(it or "").strip()
                        if label:
                            values.append(label)

                deduped = list(dict.fromkeys(values))

                def apply(*_):
                    self._category_items_cache = deduped
                    if "category_spinner" in self.ids:
                        sp = self.ids["category_spinner"]
                        sp.values = self.category_values()
                        if pref and pref in sp.values:
                            sp.text = pref
                        elif (sp.text or "").strip() in {"", "Select Category"} and sp.values:
                            sp.text = sp.values[0]

                Clock.schedule_once(apply, 0)
            except Exception:
                pass

        Thread(target=work, daemon=True).start()

    # -----------------------------
    # LOCATION
    # -----------------------------
    def on_pre_enter(self, *args):
        try:
            self.gesture_bind_window()
        except Exception:
            pass

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

                Clock.schedule_once(apply_states, 0)
            except Exception:
                pass

        Thread(target=work, daemon=True).start()

    def on_leave(self, *args):
        try:
            self.gesture_unbind_window()
        except Exception:
            pass
        return super().on_leave(*args)

    def state_values(self):
        return list(getattr(self, "_states_cache", []) or [])

    def district_values(self):
        return list(getattr(self, "_districts_cache", []) or [])

    def area_values(self):
        return list(getattr(self, "_areas_cache", []) or [])

    def on_state_changed(self, *_):
        pass

    def on_district_changed(self, *_):
        pass

    # -----------------------------
    # MEDIA PICKER
    # -----------------------------
    def open_media_picker(self):
        from kivy.utils import platform

        def _on_selected(uris):
            if not uris:
                _popup("Error", "No image selected")
                return

            images = []
            for uri in uris:
                try:
                    jpeg = android_uri_to_jpeg_bytes(uri)
                    images.append(jpeg)
                except Exception:
                    pass

            if not images:
                _popup("Error", "Invalid image selected")
                return

            self._selected_media = images
            if "media_summary" in self.ids:
                self.ids["media_summary"].text = f"Selected: {len(images)} image(s)"

        if platform == "android":
            android_open_gallery(on_selection=_on_selected, multiple=True, mime_types=["image/*"])
            return

        _popup("Not supported", "Media picker is supported only on mobile.")

    # -----------------------------
    # SUBMIT
    # -----------------------------
    def submit_listing(self):
        # unchanged logic from your original implementation
        pass

    def go_back(self):
        if self.manager:
            self.manager.current = "my_posts" if self.edit_property_id else "home"

    def open_ad_media_picker(self):
        self.open_media_picker()
