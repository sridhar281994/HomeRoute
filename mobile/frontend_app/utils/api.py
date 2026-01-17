from __future__ import annotations

import os
from typing import Any

import certifi
import requests
from kivy.utils import platform

from frontend_app.utils.storage import get_token
from frontend_app.utils.storage import get_api_base_url


class ApiError(Exception):
    pass


def _base_url() -> str:
    # 1) Build-time/runtime override via env (useful for local dev/CI).
    env = (os.environ.get("API_BASE_URL") or "").strip()
    if env:
        return env.rstrip("/")

    # 2) Persisted app config (needed on Android devices).
    saved = (get_api_base_url() or "").strip()
    if saved:
        return saved.rstrip("/")

    # 3) Dev fallback.
    default = "http://127.0.0.1:8000"
    # On real devices localhost points to the device itself; fail with a clear message.
    if platform == "android":
        raise ApiError(
            "API is not configured.\n\n"
            "Open Login → API Settings and set your backend URL (HTTPS), e.g. https://api.yourdomain.com"
        )
    return default.rstrip("/")


def to_api_url(url: str) -> str:
    u = str(url or "").strip()
    if not u:
        return ""
    if u.startswith("http://") or u.startswith("https://") or u.startswith("//"):
        return u
    if u.startswith("/"):
        return f"{_base_url()}{u}"
    return f"{_base_url()}/{u}"


def _headers() -> dict[str, str]:
    h = {"Accept": "application/json"}
    token = get_token()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _handle(resp: requests.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except Exception:
        data = {"detail": resp.text}
    if resp.status_code >= 400:
        raise ApiError(data.get("detail") or data.get("message") or f"HTTP {resp.status_code}")
    return data


def _verify_ca_bundle() -> str:
    """
    Ensure Android builds verify HTTPS with a packaged CA bundle.
    """
    return certifi.where()


# -----------------------
# Metadata
# -----------------------
def api_meta_categories() -> dict[str, Any]:
    url = f"{_base_url()}/meta/categories"
    resp = requests.get(url, timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


# -----------------------
# Locations
# -----------------------
def api_location_states() -> dict[str, Any]:
    url = f"{_base_url()}/locations/states"
    resp = requests.get(url, timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


def api_location_districts(*, state: str) -> dict[str, Any]:
    url = f"{_base_url()}/locations/districts"
    resp = requests.get(url, params={"state": state}, timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


def api_location_areas(*, state: str, district: str) -> dict[str, Any]:
    url = f"{_base_url()}/locations/areas"
    resp = requests.get(url, params={"state": state, "district": district}, timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


# -----------------------
# Auth
# -----------------------
def api_register(
    *,
    email: str,
    phone: str,
    password: str,
    name: str,
    state: str,
    district: str,
    role: str,
    owner_category: str = "",
) -> dict[str, Any]:
    url = f"{_base_url()}/auth/register"
    resp = requests.post(
        url,
        json={
            "email": email,
            "phone": phone,
            "username": phone,  # keep server-side compatibility / uniqueness
            "password": password,
            "name": name,
            "state": state,
            "district": district,
            "role": role,
            "owner_category": owner_category,
        },
        timeout=15,
        verify=_verify_ca_bundle(),
    )
    return _handle(resp)


def api_login_request_otp(*, identifier: str, password: str) -> dict[str, Any]:
    url = f"{_base_url()}/auth/login/request-otp"
    resp = requests.post(url, json={"identifier": identifier, "password": password}, timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


def api_login_verify_otp(*, identifier: str, password: str, otp: str) -> dict[str, Any]:
    url = f"{_base_url()}/auth/login/verify-otp"
    resp = requests.post(
        url, json={"identifier": identifier, "password": password, "otp": otp}, timeout=15, verify=_verify_ca_bundle()
    )
    return _handle(resp)


def api_guest() -> dict[str, Any]:
    url = f"{_base_url()}/auth/guest"
    resp = requests.post(url, json={}, timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


def api_forgot_password_request_otp(*, identifier: str) -> dict[str, Any]:
    url = f"{_base_url()}/auth/forgot/request-otp"
    resp = requests.post(url, json={"identifier": identifier}, timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


def api_forgot_password_reset(*, identifier: str, otp: str, new_password: str) -> dict[str, Any]:
    url = f"{_base_url()}/auth/forgot/reset"
    resp = requests.post(
        url,
        json={"identifier": identifier, "otp": otp, "new_password": new_password},
        timeout=15,
        verify=_verify_ca_bundle(),
    )
    return _handle(resp)


# -----------------------
# Properties
# -----------------------
def api_list_properties(*, q: str = "", rent_sale: str = "", property_type: str = "", max_price: str = "") -> dict[str, Any]:
    url = f"{_base_url()}/properties"
    rent_sale_norm = (rent_sale or "").strip()
    rent_sale_norm = rent_sale_norm.lower()
    params = {
        "q": q or None,
        "rent_sale": (rent_sale_norm if rent_sale_norm and rent_sale_norm != "any" else None),
        "property_type": (property_type if property_type and property_type.lower() != "any" else None),
        "max_price": (max_price or None),
    }
    resp = requests.get(url, params=params, headers=_headers(), timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


def api_get_property(property_id: int) -> dict[str, Any]:
    url = f"{_base_url()}/properties/{int(property_id)}"
    resp = requests.get(url, headers=_headers(), timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


def api_get_property_contact(property_id: int) -> dict[str, Any]:
    url = f"{_base_url()}/properties/{int(property_id)}/contact"
    resp = requests.get(url, headers=_headers(), timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


def api_owner_create_property(*, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Owner listing creation.
    Backend endpoint: POST /owner/properties
    """
    url = f"{_base_url()}/owner/properties"
    resp = requests.post(url, json=payload, headers=_headers(), timeout=20, verify=_verify_ca_bundle())
    return _handle(resp)


def api_upload_property_media(*, property_id: int, file_path: str, sort_order: int = 0) -> dict[str, Any]:
    """
    Upload an image/video for a property listing.
    Backend endpoint: POST /properties/{property_id}/images
    """
    url = f"{_base_url()}/properties/{int(property_id)}/images"
    with open(file_path, "rb") as f:
        files = {"file": (os.path.basename(file_path), f)}
        resp = requests.post(
            url,
            params={"sort_order": int(sort_order)},
            files=files,
            headers=_headers(),
            timeout=60,
            verify=_verify_ca_bundle(),
        )
    return _handle(resp)

# -----------------------
# Subscription
# -----------------------
def api_subscription_status() -> dict[str, Any]:
    url = f"{_base_url()}/me/subscription"
    resp = requests.get(url, headers=_headers(), timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


# -----------------------
# Me / Profile
# -----------------------
def api_me() -> dict[str, Any]:
    url = f"{_base_url()}/me"
    resp = requests.get(url, headers=_headers(), timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


def api_me_update(*, name: str) -> dict[str, Any]:
    url = f"{_base_url()}/me"
    resp = requests.patch(url, json={"name": name}, headers=_headers(), timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


def api_me_upload_profile_image(*, file_path: str) -> dict[str, Any]:
    url = f"{_base_url()}/me/profile-image"
    with open(file_path, "rb") as f:
        files = {"file": (os.path.basename(file_path), f)}
        resp = requests.post(url, files=files, headers=_headers(), timeout=30, verify=_verify_ca_bundle())
    return _handle(resp)


def api_me_change_email_request_otp(*, new_email: str) -> dict[str, Any]:
    url = f"{_base_url()}/me/change-email/request-otp"
    resp = requests.post(url, json={"new_email": new_email}, headers=_headers(), timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


def api_me_change_email_verify(*, new_email: str, otp: str) -> dict[str, Any]:
    url = f"{_base_url()}/me/change-email/verify"
    resp = requests.post(
        url, json={"new_email": new_email, "otp": otp}, headers=_headers(), timeout=15, verify=_verify_ca_bundle()
    )
    return _handle(resp)


def api_me_change_phone_request_otp(*, new_phone: str) -> dict[str, Any]:
    url = f"{_base_url()}/me/change-phone/request-otp"
    resp = requests.post(url, json={"new_phone": new_phone}, headers=_headers(), timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


def api_me_change_phone_verify(*, new_phone: str, otp: str) -> dict[str, Any]:
    url = f"{_base_url()}/me/change-phone/verify"
    resp = requests.post(
        url, json={"new_phone": new_phone, "otp": otp}, headers=_headers(), timeout=15, verify=_verify_ca_bundle()
    )
    return _handle(resp)


def api_me_delete() -> dict[str, Any]:
    url = f"{_base_url()}/me"
    resp = requests.delete(url, headers=_headers(), timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)

