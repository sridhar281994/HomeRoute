from __future__ import annotations

import os
import time
import json
import mimetypes
from contextlib import ExitStack
from typing import Any

import certifi
import requests

from frontend_app.utils.storage import get_token

# Production API base URL (override with HOME_ROUTE_API_BASE_URL).
API_BASE_URL = os.environ.get("HOME_ROUTE_API_BASE_URL") or "https://homeroute-pt0c.onrender.com"
DEFAULT_TIMEOUT = (10, 35)
CONNECT_RETRIES = 2
RETRY_BACKOFF_SECONDS = 0.6
_SESSION = requests.Session()


class ApiError(Exception):
    pass


def _normalize_base_url(value: str) -> str:
    url = (value or "").strip().rstrip("/")
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    return f"https://{url}"


def _base_url() -> str:
    return _normalize_base_url(API_BASE_URL)


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


def _guess_content_type(filename: str) -> str:
    """
    Mobile uploads often include modern formats (AVIF/HEIC) that Python's
    `mimetypes` may not know by default. Ensure we send a correct part
    content-type so the backend can process and Cloudinary can detect format.
    """
    name = (filename or "").strip()
    ct = mimetypes.guess_type(name)[0]
    if ct:
        return ct.strip()
    ext = os.path.splitext(name.lower())[1]
    return {
        ".heic": "image/heic",
        ".heif": "image/heif",
        ".avif": "image/avif",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
    }.get(ext, "application/octet-stream")


def _request(method: str, url: str, **kwargs) -> requests.Response:
    timeout = kwargs.pop("timeout", DEFAULT_TIMEOUT)
    verify = kwargs.pop("verify", _verify_ca_bundle())
    last_exc: Exception | None = None
    for attempt in range(CONNECT_RETRIES + 1):
        try:
            return _SESSION.request(method, url, timeout=timeout, verify=verify, **kwargs)
        except requests.exceptions.ConnectionError as exc:
            last_exc = exc
            if attempt >= CONNECT_RETRIES:
                raise
            time.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
    if last_exc:
        raise last_exc
    raise requests.exceptions.ConnectionError("Request failed")


# -----------------------
# Metadata
# -----------------------
def api_meta_categories() -> dict[str, Any]:
    url = f"{_base_url()}/meta/categories"
    resp = _request("GET", url, timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


# -----------------------
# Locations
# -----------------------
def api_location_states() -> dict[str, Any]:
    url = f"{_base_url()}/locations/states"
    resp = _request("GET", url, timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


def api_location_districts(*, state: str) -> dict[str, Any]:
    url = f"{_base_url()}/locations/districts"
    resp = _request("GET", url, params={"state": state}, timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


def api_location_areas(*, state: str, district: str) -> dict[str, Any]:
    url = f"{_base_url()}/locations/areas"
    resp = _request("GET", url, params={"state": state, "district": district}, timeout=15, verify=_verify_ca_bundle())
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
    resp = _request(
        "POST",
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
    resp = _request(
        "POST", url, json={"identifier": identifier, "password": password}, timeout=DEFAULT_TIMEOUT, verify=_verify_ca_bundle()
    )
    return _handle(resp)


def api_login_verify_otp(*, identifier: str, password: str, otp: str) -> dict[str, Any]:
    url = f"{_base_url()}/auth/login/verify-otp"
    resp = _request(
        "POST", url, json={"identifier": identifier, "password": password, "otp": otp}, timeout=DEFAULT_TIMEOUT, verify=_verify_ca_bundle()
    )
    return _handle(resp)


def api_login_google(*, id_token: str) -> dict[str, Any]:
    """
    Login/register via Google Sign-In ID token.
    Backend endpoint: POST /auth/google
    """
    url = f"{_base_url()}/auth/google"
    resp = _request("POST", url, json={"id_token": id_token}, timeout=20, verify=_verify_ca_bundle())
    return _handle(resp)


def api_guest() -> dict[str, Any]:
    url = f"{_base_url()}/auth/guest"
    resp = _request("POST", url, json={}, timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


def api_forgot_password_request_otp(*, identifier: str) -> dict[str, Any]:
    url = f"{_base_url()}/auth/forgot/request-otp"
    resp = _request("POST", url, json={"identifier": identifier}, timeout=DEFAULT_TIMEOUT, verify=_verify_ca_bundle())
    return _handle(resp)


def api_forgot_password_reset(*, identifier: str, otp: str, new_password: str) -> dict[str, Any]:
    url = f"{_base_url()}/auth/forgot/reset"
    resp = _request(
        "POST",
        url,
        json={"identifier": identifier, "otp": otp, "new_password": new_password},
        timeout=DEFAULT_TIMEOUT,
        verify=_verify_ca_bundle(),
    )
    return _handle(resp)


# -----------------------
# Properties
# -----------------------
def api_list_properties(
    *,
    q: str = "",
    rent_sale: str = "",
    property_type: str = "",
    post_group: str = "",
    max_price: str = "",
    state: str = "",
    district: str = "",
    area: str = "",
    sort_budget: str = "",
    posted_within_days: str = "",
) -> dict[str, Any]:
    url = f"{_base_url()}/properties"
    rent_sale_norm = (rent_sale or "").strip()
    rent_sale_norm = rent_sale_norm.lower()
    sort_budget_norm = (sort_budget or "").strip().lower()
    params = {
        "q": q or None,
        "rent_sale": (rent_sale_norm if rent_sale_norm and rent_sale_norm != "any" else None),
        "property_type": (property_type if property_type and property_type.lower() != "any" else None),
        "post_group": ((post_group or "").strip().lower() or None),
        "max_price": (max_price or None),
        "state": ((state or "").strip() or None),
        "district": ((district or "").strip() or None),
        "area": ((area or "").strip() or None),
        "sort_budget": (sort_budget_norm or None),
        "posted_within_days": ((posted_within_days or "").strip() or None),
    }
    resp = _request("GET", url, params=params, headers=_headers(), timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


def api_list_nearby_properties(
    *,
    lat: float,
    lon: float,
    radius_km: int | None = None,
    q: str = "",
    rent_sale: str = "",
    property_type: str = "",
    post_group: str = "",
    max_price: str = "",
    state: str = "",
    district: str = "",
    area: str = "",
    posted_within_days: str = "",
    limit: int | None = None,
) -> dict[str, Any]:
    """
    Nearby listing based on GPS.
    Backend endpoint: GET /properties/nearby
    """
    url = f"{_base_url()}/properties/nearby"
    rent_sale_norm = (rent_sale or "").strip().lower()
    params = {
        "lat": float(lat),
        "lon": float(lon),
        "radius_km": int(radius_km) if radius_km is not None else None,
        "q": (q or "").strip() or None,
        "rent_sale": (rent_sale_norm or None),
        "property_type": (property_type if property_type and property_type.lower() != "any" else None),
        "post_group": ((post_group or "").strip().lower() or None),
        "max_price": (max_price or None),
        "state": ((state or "").strip() or None),
        "district": ((district or "").strip() or None),
        "area": ((area or "").strip() or None),
        "posted_within_days": ((posted_within_days or "").strip() or None),
        "limit": int(limit) if limit is not None else None,
    }
    resp = _request("GET", url, params=params, headers=_headers(), timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


def api_owner_list_properties() -> dict[str, Any]:
    """
    Owner's own listings.
    Backend endpoint: GET /owner/properties
    """
    url = f"{_base_url()}/owner/properties"
    resp = _request("GET", url, headers=_headers(), timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


def api_get_property(property_id: int) -> dict[str, Any]:
    url = f"{_base_url()}/properties/{int(property_id)}"
    resp = _request("GET", url, headers=_headers(), timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


def api_get_property_contact(property_id: int) -> dict[str, Any]:
    url = f"{_base_url()}/properties/{int(property_id)}/contact"
    resp = _request("GET", url, headers=_headers(), timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


def api_owner_create_property(*, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Owner listing creation.
    Backend endpoint: POST /owner/properties
    """
    url = f"{_base_url()}/owner/properties"
    resp = _request("POST", url, json=payload, headers=_headers(), timeout=20, verify=_verify_ca_bundle())
    return _handle(resp)


def api_owner_publish_property(*, payload: dict[str, Any], file_paths: list[str]) -> dict[str, Any]:
    """
    Atomic publish (create + upload media).
    Backend endpoint: POST /owner/properties/publish
    """
    url = f"{_base_url()}/owner/properties/publish"
    # Server expects multipart:
    # - payload: JSON string
    # - files: repeated file parts
    form = {"payload": json.dumps(payload or {}, ensure_ascii=False)}

    paths = list(file_paths or [])
    with ExitStack() as stack:
        files: list[tuple[str, tuple[str, Any, str]]] = []
        for fp in paths:
            f = stack.enter_context(open(fp, "rb"))
            fname = os.path.basename(fp)
            ctype = _guess_content_type(fname)
            files.append(("files", (fname, f, ctype)))
        resp = _request(
            "POST",
            url,
            data=form,
            files=files,
            headers=_headers(),
            timeout=120,
            verify=_verify_ca_bundle(),
        )
    return _handle(resp)

def api_owner_publish_property_bytes(*, payload: dict[str, Any], files_bytes: list[bytes]) -> dict[str, Any]:
    """
    Atomic publish (create + upload) using in-memory bytes (Android-safe).
    Backend endpoint: POST /owner/properties/publish
    """
    url = f"{_base_url()}/owner/properties/publish"

    form = {"payload": json.dumps(payload or {}, ensure_ascii=False)}

    files: list[tuple[str, tuple[str, Any, str]]] = []
    for i, b in enumerate(files_bytes or []):
        files.append(
            (
                "files",
                (f"image_{i}.jpg", b, "image/jpeg"),
            )
        )

    resp = _request(
        "POST",
        url,
        data=form,
        files=files,
        headers=_headers(),
        timeout=120,
        verify=_verify_ca_bundle(),
    )
    return _handle(resp)

def api_owner_update_property(*, property_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Owner listing edit.
    Backend endpoint: PATCH /owner/properties/{property_id}
    """
    url = f"{_base_url()}/owner/properties/{int(property_id)}"
    resp = _request("PATCH", url, json=payload, headers=_headers(), timeout=20, verify=_verify_ca_bundle())
    return _handle(resp)


def api_owner_delete_property(*, property_id: int) -> dict[str, Any]:
    """
    Owner listing delete.
    Backend endpoint: DELETE /owner/properties/{property_id}
    """
    url = f"{_base_url()}/owner/properties/{int(property_id)}"
    resp = _request("DELETE", url, headers=_headers(), timeout=20, verify=_verify_ca_bundle())
    return _handle(resp)


def api_upload_property_media(*, property_id: int, file_path: str, sort_order: int = 0) -> dict[str, Any]:
    """
    Upload an image/video for a property listing.
    Backend endpoint: POST /properties/{property_id}/images
    """
    url = f"{_base_url()}/properties/{int(property_id)}/images"
    with open(file_path, "rb") as f:
        fname = os.path.basename(file_path)
        files = {"file": (fname, f, _guess_content_type(fname))}
        resp = _request(
            "POST",
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
    resp = _request("GET", url, headers=_headers(), timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


def api_subscription_summary(*, window_days: int = 30) -> dict[str, Any]:
    url = f"{_base_url()}/me/subscription/summary"
    resp = _request(
        "GET",
        url,
        params={"window_days": int(window_days)},
        headers=_headers(),
        timeout=15,
        verify=_verify_ca_bundle(),
    )
    return _handle(resp)


# -----------------------
# Me / Profile
# -----------------------
def api_me() -> dict[str, Any]:
    url = f"{_base_url()}/me"
    resp = _request("GET", url, headers=_headers(), timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


def api_me_update(*, name: str) -> dict[str, Any]:
    url = f"{_base_url()}/me"
    resp = _request("PATCH", url, json={"name": name}, headers=_headers(), timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)


def api_me_upload_profile_image(*, file_path: str) -> dict[str, Any]:
    url = f"{_base_url()}/me/profile-image"
    with open(file_path, "rb") as f:
        fname = os.path.basename(file_path)
        files = {"file": (fname, f, _guess_content_type(fname))}
        resp = _request("POST", url, files=files, headers=_headers(), timeout=30, verify=_verify_ca_bundle())
    return _handle(resp)

def api_me_upload_profile_image_bytes(*, raw: bytes) -> dict[str, Any]:
    """
    Upload profile image using in-memory JPEG bytes (Android-safe).
    Backend endpoint: POST /me/profile-image
    """
    url = f"{_base_url()}/me/profile-image"

    files = {
        "file": ("profile.jpg", raw, "image/jpeg"),
    }

    resp = _request(
        "POST",
        url,
        files=files,
        headers=_headers(),
        timeout=60,
        verify=_verify_ca_bundle(),
    )
    return _handle(resp)




def api_me_change_email_request_otp(*, new_email: str) -> dict[str, Any]:
    url = f"{_base_url()}/me/change-email/request-otp"
    resp = _request(
        "POST", url, json={"new_email": new_email}, headers=_headers(), timeout=DEFAULT_TIMEOUT, verify=_verify_ca_bundle()
    )
    return _handle(resp)


def api_me_change_email_verify(*, new_email: str, otp: str) -> dict[str, Any]:
    url = f"{_base_url()}/me/change-email/verify"
    resp = _request(
        "POST",
        url,
        json={"new_email": new_email, "otp": otp},
        headers=_headers(),
        timeout=DEFAULT_TIMEOUT,
        verify=_verify_ca_bundle(),
    )
    return _handle(resp)


def api_me_change_phone_request_otp(*, new_phone: str) -> dict[str, Any]:
    url = f"{_base_url()}/me/change-phone/request-otp"
    resp = _request(
        "POST", url, json={"new_phone": new_phone}, headers=_headers(), timeout=DEFAULT_TIMEOUT, verify=_verify_ca_bundle()
    )
    return _handle(resp)


def api_me_change_phone_verify(*, new_phone: str, otp: str) -> dict[str, Any]:
    url = f"{_base_url()}/me/change-phone/verify"
    resp = _request(
        "POST",
        url,
        json={"new_phone": new_phone, "otp": otp},
        headers=_headers(),
        timeout=DEFAULT_TIMEOUT,
        verify=_verify_ca_bundle(),
    )
    return _handle(resp)


def api_me_delete() -> dict[str, Any]:
    url = f"{_base_url()}/me"
    resp = _request("DELETE", url, headers=_headers(), timeout=15, verify=_verify_ca_bundle())
    return _handle(resp)

