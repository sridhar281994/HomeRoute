from threading import Thread
import re
import os

from kivy.clock import Clock
from kivy.properties import StringProperty
from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen

from frontend_app.utils.api import ApiError, api_location_districts, api_location_states, api_register, api_login_google
from frontend_app.utils.google_signin import google_sign_in
from frontend_app.utils.storage import get_session, set_session

# Email regex
EMAIL_RE = re.compile(r"[^@]+@[^@]+\.[^@]+")
DEFAULT_GOOGLE_OAUTH_CLIENT_ID = "333176294914-t7b1h2ams20nn0dvf2k4n5cedq71q8dm.apps.googleusercontent.com"


class RegisterScreen(Screen):
    # Source of truth for the segmented control (Owner/Customer).
    # KV binds the toggle button "state" to this property so the active styling
    # cannot drift to the wrong button.
    role = StringProperty("customer")

    OWNER_CATEGORIES: list[str] = [
        # Property & Real Estate
        "Apartment Owner",
        "Villa Owner",
        "Plot Owner",
        "PG Owner",
        "Marriage Hall Owner",
        "Party Hall Owner",
        # Construction & Materials
        "Retailer / Hardware Shop",
        "Steel Supplier",
        "Brick Supplier",
        "Sand Supplier",
        "M-Sand Supplier",
        "Cement Supplier",
        # Services & Workforce
        "Interior Designer",
        "Carpenter / Wood Works",
        "Mason / Labor Contractor",
        "Electrician",
        "Plumber",
        "Painter",
        "Gardener / Landscaping",
        "Cleaning Services",
    ]

    @staticmethod
    def _popup(title: str, msg: str) -> None:
        """Non-blocking popup helper (safe from worker threads)."""
        def _open(*_):
            Popup(
                title=title,
                content=Label(text=msg),
                size_hint=(0.7, 0.3),
                auto_dismiss=True,
            ).open()
        Clock.schedule_once(_open, 0)

    def on_pre_enter(self, *args) -> None:
        """
        Ensure spinners have values whenever the screen opens.
        This avoids cases where District dropdown stays empty until state changes.
        """
        # Ensure the role segmented control reflects the stored value (prevents
        # the "active color" appearing on the wrong button after navigation).
        def _sync_role(*_):
            try:
                role = (self._get("role_value") or self.role or "customer").strip().lower()
            except Exception:
                role = "customer"
            self.set_role(role)

        Clock.schedule_once(_sync_role, 0)

        # Populate State/District lists from backend.
        from threading import Thread

        def work():
            try:
                st = api_location_states().get("items") or []
                st = [str(x).strip() for x in st if str(x).strip()]

                def apply_states(*_):
                    self._states_cache = st
                    if "country_spinner" in self.ids:
                        sp = self.ids["country_spinner"]
                        sp.values = self.country_values()
                        try:
                            sp.unbind(text=self.on_state_changed)  # type: ignore[arg-type]
                        except Exception:
                            pass
                        try:
                            sp.bind(text=self.on_state_changed)  # type: ignore[arg-type]
                        except Exception:
                            pass
                        # Default to "Any" (no filtering). Do not auto-select a real state
                        # because that triggers district fetches and confuses users.
                        if (sp.text or "").strip() in {"Select Country", "Select State", "", "Any"}:
                            if "Any" in sp.values:
                                sp.text = "Any"

                    # Trigger districts population based on selected state
                    self.on_state_changed()

                Clock.schedule_once(apply_states, 0)
            except Exception:
                # Non-fatal: keep spinners empty if offline.
                Clock.schedule_once(lambda *_: setattr(self, "_states_cache", []), 0)

        Thread(target=work, daemon=True).start()

    def go_back(self) -> None:
        """Navigate back to login or stage screen."""
        self.manager.current = "login"

    def _get(self, wid: str) -> str:
        """Helper to get and trim text from widget by ID."""
        w = self.ids.get(wid)
        return (w.text or "").strip() if w else ""

    def _validate(self, phone: str, email: str, password: str) -> str | None:
        """Basic validation for registration fields."""
        if not EMAIL_RE.match(email):
            return "Enter a valid email address."
        if not phone:
            return "Enter your phone number."
        digits = "".join(ch for ch in phone if ch.isdigit())
        if len(digits) < 8 or len(digits) > 15:
            return "Enter a valid phone number."
        if len(password) < 6:
            return "Password must be at least 6 characters."
        return None

    def save_profile(self) -> None:
        """Collects input, validates, and calls register API."""
        name = self._get("name_input")
        phone = self._get("phone_input")
        email = self._get("email_input")
        password = self._get("password_input")
        state = (self.ids.get("country_spinner").text or "").strip() if self.ids.get("country_spinner") else ""
        district = (self.ids.get("district_spinner").text or "").strip() if self.ids.get("district_spinner") else ""
        role = (self._get("role_value") or "customer").strip().lower()
        owner_category = (self.ids.get("owner_category_spinner").text or "").strip() if self.ids.get("owner_category_spinner") else ""

        err = self._validate(phone, email, password)
        if err:
            self._popup("Invalid", err)
            return

        if not name:
            self._popup("Invalid", "Please enter your full name.")
            return
        # State/District are optional for registration. UI defaults to "Any".
        state_norm = "" if state in {"Select Country", "Select State", "Any"} else state
        district_norm = "" if district in {"Select District", "Any"} else district
        if role not in {"owner", "customer"}:
            self._popup("Invalid", "Please select role: Owner or Customer.")
            return
        api_role = "owner" if role == "owner" else "user"
        if api_role == "owner" and (not owner_category or owner_category in {"Select Category"}):
            self._popup("Invalid", "Please select your business category.")
            return

        # Truncate password safely to 72 bytes for bcrypt
        password_safe = password.encode("utf-8")[:72].decode("utf-8", errors="ignore")

        def work():
            try:
                res = api_register(
                    email=email,
                    phone=phone,
                    password=password_safe,
                    name=name.strip(),
                    state=state_norm,
                    district=district_norm,
                    role=api_role,
                    owner_category=(owner_category if api_role == "owner" else ""),
                )

                if res.get("ok"):
                    def done_ok(*_):
                        self._popup("Success", "Registered successfully. Please login.")
                        self.manager.current = "login"
                    Clock.schedule_once(done_ok, 0)
                else:
                    msg = res.get("detail") or res.get("message") or "Registration failed."
                    self._popup("Error", msg)

            except ApiError as e:
                self._popup("Error", str(e))

        Thread(target=work, daemon=True).start()

    def google_login(self) -> None:
        """
        Google Sign-In (Android):
        - Launch Google account picker
        - Send ID token to backend (/auth/google)
        - Store session and navigate to home
        """
        server_client_id = (
            os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
            or os.environ.get("GOOGLE_WEB_CLIENT_ID")
            or DEFAULT_GOOGLE_OAUTH_CLIENT_ID
        ).strip()

        def on_error(msg: str) -> None:
            self._popup("Google Login", msg or "Google login failed.")

        def on_success(id_token: str, profile: dict[str, str]) -> None:
            # Exchange token with backend (network call off the UI thread).
            def work():
                try:
                    data = api_login_google(id_token=id_token)
                    token = data.get("access_token")
                    user = data.get("user") or {}
                    if not token:
                        raise ApiError("Google login failed.")

                    sess = get_session() or {}
                    set_session(token=str(token), user=dict(user), remember=bool(sess.get("remember_me") or False))

                    def after(*_):
                        self._popup("Success", f"Logged in as {user.get('name') or profile.get('email') or 'Google user'}.")
                        if self.manager:
                            self.manager.current = "home"

                    Clock.schedule_once(after, 0)
                except ApiError as e:
                    self._popup("Google Login", str(e))
                except Exception as e:
                    self._popup("Google Login", str(e) or "Network error. Please try again.")

            Thread(target=work, daemon=True).start()

        google_sign_in(server_client_id=server_client_id, on_success=on_success, on_error=on_error)

    def country_values(self):
        st = list(getattr(self, "_states_cache", []) or [])
        # Keep "Any" as a stable first option.
        return ["Any"] + [x for x in st if x and str(x).strip() and str(x).strip() != "Any"]

    def district_values(self):
        ds = list(getattr(self, "_districts_cache", []) or [])
        return ["Any"] + [x for x in ds if x and str(x).strip() and str(x).strip() != "Any"]

    def on_state_changed(self, *_):
        # When state changes, fetch districts from backend.
        if "district_spinner" not in self.ids:
            return
        state = (self.ids.get("country_spinner").text or "").strip() if self.ids.get("country_spinner") else ""
        if (not state) or state in {"Select Country", "Select State", "Any"}:
            self._districts_cache = []
            try:
                self.ids["district_spinner"].values = []
                # Keep District at "Any" when State is not selected.
                self.ids["district_spinner"].text = "Any"
            except Exception:
                pass
            return

        from threading import Thread

        def work():
            try:
                ds = api_location_districts(state=state).get("items") or []
                ds = [str(x).strip() for x in ds if str(x).strip()]

                def apply(*_):
                    self._districts_cache = ds
                    try:
                        self.ids["district_spinner"].values = self.district_values()
                        # Reset district to "Any" on state change.
                        self.ids["district_spinner"].text = "Any"
                    except Exception:
                        pass

                Clock.schedule_once(apply, 0)
            except ApiError as e:
                self._popup("Error", str(e))
            except Exception:
                Clock.schedule_once(lambda *_: setattr(self, "_districts_cache", []), 0)

        Thread(target=work, daemon=True).start()

    def owner_category_values(self):
        return list(self.OWNER_CATEGORIES)

    def set_role(self, role_value: str) -> None:
        """
        KV helper: store role in a hidden TextInput id `role_value` and toggle owner-category UI.
        """
        role_value = (role_value or "").strip().lower()
        if role_value not in {"owner", "customer"}:
            role_value = "customer"

        # Prevent recursion when we programmatically flip ToggleButton states.
        if getattr(self, "_applying_role", False):
            return
        self._applying_role = True

        # Source-of-truth for KV bindings.
        self.role = role_value

        if "role_value" in self.ids:
            self.ids["role_value"].text = role_value
        try:
            is_owner = role_value == "owner"
            if "owner_category_box" in self.ids:
                self.ids["owner_category_box"].opacity = 1 if is_owner else 0
                self.ids["owner_category_box"].height = self.ids["owner_category_box"].minimum_height if is_owner else 0
                self.ids["owner_category_box"].disabled = not is_owner

            # Enforce segmented-control visual state deterministically
            # (also keeps behavior consistent if KV is loaded without bindings).
            owner_btn = self.ids.get("role_owner_btn")
            customer_btn = self.ids.get("role_customer_btn")
            if owner_btn is not None and customer_btn is not None:
                if is_owner:
                    customer_btn.state = "normal"
                    owner_btn.state = "down"
                else:
                    owner_btn.state = "normal"
                    customer_btn.state = "down"
        except Exception:
            pass
        finally:
            self._applying_role = False
