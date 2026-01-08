from __future__ import annotations

import os
from typing import Any

import requests

from frontend_app.utils.storage import get_token


class ApiError(Exception):
    pass


def _base_url() -> str:
    return (os.environ.get("API_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")


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


# -----------------------
# Auth
# -----------------------
def api_register(*, email: str, username: str, password: str, name: str, country: str, gender: str) -> dict[str, Any]:
    url = f"{_base_url()}/auth/register"
    resp = requests.post(
        url,
        json={
            "email": email,
            "username": username,
            "password": password,
            "name": name,
            "country": country,
            "gender": gender,
        },
        timeout=15,
    )
    return _handle(resp)


def api_login_request_otp(*, identifier: str, password: str) -> dict[str, Any]:
    url = f"{_base_url()}/auth/login/request-otp"
    resp = requests.post(url, json={"identifier": identifier, "password": password}, timeout=15)
    return _handle(resp)


def api_login_verify_otp(*, identifier: str, password: str, otp: str) -> dict[str, Any]:
    url = f"{_base_url()}/auth/login/verify-otp"
    resp = requests.post(url, json={"identifier": identifier, "password": password, "otp": otp}, timeout=15)
    return _handle(resp)


def api_guest() -> dict[str, Any]:
    url = f"{_base_url()}/auth/guest"
    resp = requests.post(url, json={}, timeout=15)
    return _handle(resp)


def api_forgot_password_request_otp(*, identifier: str) -> dict[str, Any]:
    url = f"{_base_url()}/auth/forgot/request-otp"
    resp = requests.post(url, json={"identifier": identifier}, timeout=15)
    return _handle(resp)


def api_forgot_password_reset(*, identifier: str, otp: str, new_password: str) -> dict[str, Any]:
    url = f"{_base_url()}/auth/forgot/reset"
    resp = requests.post(url, json={"identifier": identifier, "otp": otp, "new_password": new_password}, timeout=15)
    return _handle(resp)


# -----------------------
# Properties
# -----------------------
def api_list_properties(*, q: str = "", rent_sale: str = "", property_type: str = "", max_price: str = "") -> dict[str, Any]:
    url = f"{_base_url()}/properties"
    params = {
        "q": q or None,
        "rent_sale": (rent_sale if rent_sale and rent_sale.lower() != "any" else None),
        "property_type": (property_type if property_type and property_type.lower() != "any" else None),
        "max_price": (max_price or None),
    }
    resp = requests.get(url, params=params, headers=_headers(), timeout=15)
    return _handle(resp)


def api_get_property(property_id: int) -> dict[str, Any]:
    url = f"{_base_url()}/properties/{int(property_id)}"
    resp = requests.get(url, headers=_headers(), timeout=15)
    return _handle(resp)


def api_get_property_contact(property_id: int) -> dict[str, Any]:
    url = f"{_base_url()}/properties/{int(property_id)}/contact"
    resp = requests.get(url, headers=_headers(), timeout=15)
    return _handle(resp)


# -----------------------
# Subscription
# -----------------------
def api_subscription_status() -> dict[str, Any]:
    url = f"{_base_url()}/me/subscription"
    resp = requests.get(url, headers=_headers(), timeout=15)
    return _handle(resp)

