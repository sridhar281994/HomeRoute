from threading import Thread
import re

from kivy.clock import Clock
from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen

from frontend_app.utils.api import ApiError, api_location_districts, api_location_states, api_register

# Email regex
EMAIL_RE = re.compile(r"[^@]+@[^@]+\.[^@]+")


class RegisterScreen(Screen):
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
                        if (sp.text or "").strip() in {"Select Country", "Select State", ""}:
                            preferred = "Tamil Nadu" if "Tamil Nadu" in sp.values else (sp.values[0] if sp.values else "")
                            if preferred:
                                sp.text = preferred

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
        if not state or state in {"Select Country", "Select State"}:
            self._popup("Invalid", "Please select your state.")
            return
        if not district or district in {"Select District"}:
            self._popup("Invalid", "Please select your district.")
            return
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
                    state=state,
                    district=district,
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

    def country_values(self):
        return list(getattr(self, "_states_cache", []) or [])

    def district_values(self):
        return list(getattr(self, "_districts_cache", []) or [])

    def on_state_changed(self, *_):
        # When state changes, fetch districts from backend.
        if "district_spinner" not in self.ids:
            return
        state = (self.ids.get("country_spinner").text or "").strip() if self.ids.get("country_spinner") else ""
        if not state or state in {"Select Country", "Select State"}:
            self._districts_cache = []
            try:
                self.ids["district_spinner"].values = []
                self.ids["district_spinner"].text = "Select District"
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
                        self.ids["district_spinner"].text = "Select District"
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
        if "role_value" in self.ids:
            self.ids["role_value"].text = role_value
        try:
            is_owner = role_value == "owner"
            if "owner_category_box" in self.ids:
                self.ids["owner_category_box"].opacity = 1 if is_owner else 0
                self.ids["owner_category_box"].height = self.ids["owner_category_box"].minimum_height if is_owner else 0
                self.ids["owner_category_box"].disabled = not is_owner
        except Exception:
            pass
