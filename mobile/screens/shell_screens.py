from __future__ import annotations

import os
from typing import Any

from kivy.clock import Clock
from kivy.factory import Factory
from kivy.properties import BooleanProperty, DictProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen

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
from frontend_app.utils.storage import clear_session, get_session, get_user, set_guest_session, set_session
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
                err_msg = str(e)
                Clock.schedule_once(lambda *_dt, err_msg=err_msg: _popup("Error", err_msg), 0)

        from threading import Thread

        Thread(target=work, daemon=True).start()

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


class SettingsScreen(Screen):
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

            self.default_profile_image = resource_find("assets/QuickRent.png") or "assets/QuickRent.png"
        except Exception:
            self.default_profile_image = "assets/QuickRent.png"

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
                err_msg = str(e)
                Clock.schedule_once(lambda *_dt, err_msg=err_msg: _popup("Error", err_msg), 0)

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


class SubscriptionScreen(Screen):
    status_text = StringProperty("Status: loading…")
    provider_text = StringProperty("")
    expires_text = StringProperty("")
    is_loading = BooleanProperty(False)

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
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._edit_data: dict[str, Any] | None = None
        self.edit_property_id: int | None = None

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
                cat = str(p.get("property_type") or "").strip().lower() or "property"
                if cat not in {"materials", "services", "property"}:
                    cat = "property"
                self.ids["category_spinner"].text = cat
            if "contact_phone_input" in self.ids:
                self.ids["contact_phone_input"].text = str(p.get("contact_phone") or p.get("phone") or "")
            if "media_summary" in self.ids:
                # Edits currently don't manage media uploads.
                self.ids["media_summary"].text = ""
        except Exception:
            return
    def on_pre_enter(self, *args):
        # Load location dropdowns from backend (and default to profile state/district if present).
        u = get_user() or {}
        p = self._edit_data or {}
        preferred_state = str(p.get("state") or u.get("state") or "").strip()
        preferred_district = str(p.get("district") or u.get("district") or "").strip()
        preferred_area = str(p.get("area") or "").strip()
        self._apply_edit_prefill()

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
                        self.manager.current = "my_posts" if self.edit_property_id else "owner_dashboard"
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
            self.manager.current = "my_posts" if self.edit_property_id else "owner_dashboard"


