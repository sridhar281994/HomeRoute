from __future__ import annotations

import datetime as dt
import base64
import hashlib
import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import tempfile
from typing import Annotated, Any
from functools import lru_cache
import math
import logging

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

import requests

from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_auth_requests

from app.config import allowed_hosts, enforce_secure_secrets, google_oauth_client_ids, otp_exp_minutes, app_env
from app.db import session_scope
from app.mailer import EmailSendError, send_email, send_otp_email
from app.rate_limit import limiter
from app.models import (
    ContactUsage,
    FreeContactUsage,
    ModerationLog,
    OtpCode,
    Property,
    PropertyImage,
    SavedProperty,
    Subscription,
    SubscriptionPlan,
    User,
    UserSubscription,
)
from app.security import create_access_token, decode_access_token, hash_password, verify_password

from app.google_play import GooglePlayNotConfigured, verify_subscription_with_google_play
from app.sms import send_sms
from app.utils.cloudinary_storage import cloudinary_enabled, destroy as cloudinary_destroy, upload_bytes as cloudinary_upload_bytes


logger = logging.getLogger(__name__)

app = FastAPI(title="Quickrent4u API")

# Production hardening: ensure we don't run with dangerous defaults.
enforce_secure_secrets()

# Optional host protection (recommend configuring ALLOWED_HOSTS in prod).
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts())


@app.middleware("http")
async def _security_headers(request, call_next):
    resp = await call_next(request)
    # Security headers (safe defaults).
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    return resp

def _cors_origins() -> list[str]:
    """
    CORS is required when the web UI is served from a different origin (e.g. Vite dev server).
    Configure with env `CORS_ORIGINS` as a comma-separated list.
    """
    raw = (os.environ.get("CORS_ORIGINS") or "").strip()
    if raw:
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        return origins
    # Reasonable local defaults (dev).
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_CATEGORY_CATALOG_PATH = os.environ.get("CATEGORY_CATALOG_PATH") or os.path.join(os.path.dirname(__file__), "category_catalog.json")

def _default_category_catalog() -> dict[str, Any]:
    # Minimal fallback if the JSON file is missing/corrupt.
    return {
        "version": "fallback",
        "updated": "",
        "categories": [
            {"group": "Property & Space", "items": ["Apartment", "Individual House / Villa", "Plot / Land", "Commercial Shop"]},
            {"group": "Construction Materials", "items": ["Cement Supplier", "Steel / TMT Supplier", "Sand Supplier", "Paint Supplier"]},
            {"group": "Construction Services", "items": ["Building Contractor", "Civil Contractor", "Interior Designer", "Electrician"]},
        ],
    }


def _load_category_catalog() -> tuple[dict[str, Any], str, str]:
    try:
        with open(_CATEGORY_CATALOG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        if data.get("categories"):
            return data, "", "file"
        return _default_category_catalog(), "Category catalog is empty; using fallback list.", "fallback"
    except Exception as exc:
        # Never break the API if the catalog file is missing/corrupt.
        return _default_category_catalog(), f"Failed to load category catalog ({exc.__class__.__name__}).", "fallback"


def _slugify(s: str) -> str:
    import re

    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def _catalog_flat_items(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for g in (catalog.get("categories") or []):
        group_label = str(g.get("group") or "").strip()
        group_id = _slugify(group_label) or "group"
        for item in (g.get("items") or []):
            label = str(item or "").strip()
            if not label:
                continue
            base_id = _slugify(label) or "item"
            item_id = base_id
            # Ensure stable uniqueness even if labels collide after slugify.
            n = 2
            while item_id in used_ids:
                item_id = f"{base_id}_{n}"
                n += 1
            used_ids.add(item_id)
            out.append(
                {
                    "id": item_id,
                    "label": label,
                    "group_id": group_id,
                    "group": group_label,
                    "search": f"{label} {group_label}".strip().lower(),
                }
            )
    return out


def _uploads_dir() -> str:
    return os.environ.get("UPLOADS_DIR") or os.path.join(os.path.dirname(__file__), "..", "uploads")


def _max_upload_image_bytes() -> int:
    # Default: 15 MB (raw upload bytes).
    try:
        return int(os.environ.get("MAX_UPLOAD_IMAGE_BYTES") or "15000000")
    except Exception:
        return 15_000_000


def _max_upload_video_bytes() -> int:
    # Default: 80 MB (raw upload bytes).
    try:
        return int(os.environ.get("MAX_UPLOAD_VIDEO_BYTES") or "80000000")
    except Exception:
        return 80_000_000


def _max_property_media_dim() -> int:
    # Max width/height for property media (pixels). Maintain aspect ratio.
    try:
        return int(os.environ.get("MAX_PROPERTY_MEDIA_DIM") or "1920")
    except Exception:
        return 1920


def _max_profile_image_dim() -> int:
    try:
        return int(os.environ.get("MAX_PROFILE_IMAGE_DIM") or "512")
    except Exception:
        return 512


def _enable_media_ai_moderation() -> bool:
    v = (os.environ.get("ENABLE_MEDIA_AI_MODERATION") or "1").strip().lower()
    return v not in {"0", "false", "no", "off"}


def _ai_moderation_fail_closed() -> bool:
    """
    If true, uploads fail when moderation cannot be performed.
    Default is fail-open to avoid blocking uploads in production when OpenAI/ffmpeg isn't configured.
    """
    v = (os.environ.get("AI_MODERATION_FAIL_CLOSED") or "0").strip().lower()
    return v in {"1", "true", "yes", "on"}


def _openai_api_key() -> str:
    return (os.environ.get("OPENAI_API_KEY") or "").strip()


def _openai_moderation_model() -> str:
    return (os.environ.get("OPENAI_MODERATION_MODEL") or "omni-moderation-latest").strip()


def _require_ai_moderation_configured() -> None:
    if not _enable_media_ai_moderation():
        return
    if not _openai_api_key():
        if _ai_moderation_fail_closed():
            raise HTTPException(status_code=503, detail="AI moderation is enabled but not configured (missing OPENAI_API_KEY)")
        # Fail-open by default to avoid breaking uploads when OpenAI isn't configured.
        return


def _openai_moderate_image(*, raw: bytes) -> dict[str, Any]:
    """
    Calls OpenAI image moderation. Returns a dict with:
      - ok: bool
      - flagged: bool
      - summary: str
      - raw: response JSON (best-effort)
    """
    if not _enable_media_ai_moderation():
        return {"ok": True, "flagged": False, "summary": "ai_moderation_disabled", "raw": {}}
    _require_ai_moderation_configured()
    if not _openai_api_key():
        return {"ok": True, "flagged": False, "summary": "ai_moderation_skipped_missing_openai_api_key", "raw": {}}

    # Use a data URL to avoid file hosting; OpenAI moderation accepts image_url inputs.
    b64 = base64.b64encode(raw).decode("ascii")
    data_url = f"data:application/octet-stream;base64,{b64}"
    payload = {
        "model": _openai_moderation_model(),
        "input": [
            {
                "type": "image_url",
                "image_url": {"url": data_url},
            }
        ],
    }

    try:
        resp = requests.post(
            "https://api.openai.com/v1/moderations",
            headers={"Authorization": f"Bearer {_openai_api_key()}", "Content-Type": "application/json"},
            json=payload,
            timeout=20,
        )
    except Exception:
        if _ai_moderation_fail_closed():
            raise HTTPException(status_code=503, detail="AI moderation service unavailable")
        return {"ok": True, "flagged": False, "summary": "ai_moderation_skipped_service_unavailable", "raw": {}}

    data: dict[str, Any] = {}
    try:
        data = resp.json()
    except Exception:
        data = {}

    if not resp.ok:
        if _ai_moderation_fail_closed():
            # Fail-closed: do not store unmoderated media.
            raise HTTPException(status_code=503, detail="AI moderation failed")
        return {
            "ok": True,
            "flagged": False,
            "summary": f"ai_moderation_skipped_http_{int(resp.status_code)}",
            "raw": data,
        }

    results = (data or {}).get("results") or []
    r0 = results[0] if results else {}
    flagged = bool((r0 or {}).get("flagged", False))

    # Build a compact summary of categories for admin logs.
    cats = (r0 or {}).get("categories") or {}
    flagged_cats = [k for k, v in cats.items() if v is True]
    summary = "flagged: " + ", ".join(flagged_cats) if flagged_cats else ("flagged" if flagged else "ok")
    return {"ok": True, "flagged": flagged, "summary": summary, "raw": data}


def _openai_moderate_video(*, raw: bytes, max_frames: int = 8) -> dict[str, Any]:
    """
    Video moderation via frame sampling + image moderation.
    Requires ffmpeg. Fail-closed if moderation cannot be performed.
    """
    if not _enable_media_ai_moderation():
        return {"ok": True, "flagged": False, "summary": "ai_moderation_disabled", "raw": {}}
    _require_ai_moderation_configured()
    if not _openai_api_key():
        return {"ok": True, "flagged": False, "summary": "ai_moderation_skipped_missing_openai_api_key", "raw": {}}
    if not shutil.which("ffmpeg"):
        if _ai_moderation_fail_closed():
            raise HTTPException(status_code=503, detail="AI moderation requires ffmpeg (missing)")
        return {"ok": True, "flagged": False, "summary": "ai_moderation_skipped_missing_ffmpeg", "raw": {}}

    with tempfile.TemporaryDirectory(prefix="ch_vid_mod_") as td:
        in_path = os.path.join(td, "in")
        out_glob = os.path.join(td, "frame_%02d.jpg")
        with open(in_path, "wb") as f:
            f.write(raw)

        # Sample 1 fps, cap frames. Keep it small for moderation.
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            in_path,
            "-vf",
            "fps=1,scale=640:-2",
            "-vframes",
            str(int(max_frames)),
            out_glob,
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid video upload")

        # Moderate each extracted frame; reject if any flagged.
        flagged_frames: list[dict[str, Any]] = []
        for i in range(1, int(max_frames) + 1):
            fp = os.path.join(td, f"frame_{i:02d}.jpg")
            if not os.path.exists(fp):
                continue
            try:
                with open(fp, "rb") as f:
                    frame = f.read()
            except Exception:
                continue
            if not frame:
                continue
            res = _openai_moderate_image(raw=frame)
            if bool(res.get("flagged")):
                flagged_frames.append({"frame": i, "summary": res.get("summary")})
                break  # fail fast

        if flagged_frames:
            return {"ok": True, "flagged": True, "summary": f"flagged_frame_{flagged_frames[0]['frame']}: {flagged_frames[0]['summary']}", "raw": {"flagged_frames": flagged_frames}}
        return {"ok": True, "flagged": False, "summary": "ok", "raw": {}}


def _raise_if_too_large(*, size_bytes: int, max_bytes: int) -> None:
    if int(size_bytes) > int(max_bytes):
        raise HTTPException(status_code=413, detail=f"Upload too large (max {max_bytes} bytes)")


def _admin_otp_email() -> str:
    """
    Admin OTPs are routed to a fixed mailbox for operational control.
    Override with env `ADMIN_OTP_EMAIL` if needed.
    """
    return (os.environ.get("ADMIN_OTP_EMAIL") or "info@srtech.co.in").strip() or "info@srtech.co.in"


def _free_contact_limit() -> int:
    try:
        return max(0, int(os.environ.get("FREE_CONTACT_LIMIT") or "5"))
    except Exception:
        return 5


def _public_image_url(file_path: str) -> str:
    """
    Convert a stored DB file path into a public URL under /uploads.

    Historical DB values may already include a leading "/uploads/" or "uploads/" prefix.
    Avoid duplicating that prefix (which would break image rendering as /uploads/uploads/...).
    """
    def _normalize_upload_rel_path(fp: str) -> str:
        """
        Normalize a stored file_path into a relative path under uploads/.

        We support historical/buggy values like:
        - "/uploads/abc.jpg"
        - "uploads/abc.jpg"
        - "/var/app/uploads/abc.jpg" (absolute path mistakenly stored)
        - "C:\\app\\uploads\\abc.jpg" (Windows path)
        - "backend/uploads/abc.jpg" (repo-relative)
        """
        fp = (fp or "").strip()
        if not fp:
            return ""
        fp = fp.replace("\\", "/")

        # If an absolute URL is stored, keep it as-is (caller will bypass).
        if fp.startswith(("http://", "https://", "//")):
            return ""

        low = fp.lower()
        # If path already contains an uploads segment, strip everything before it.
        idx = low.rfind("/uploads/")
        if idx >= 0:
            return fp[idx + len("/uploads/") :].lstrip("/")
        idx2 = low.rfind("uploads/")
        if idx2 >= 0:
            return fp[idx2 + len("uploads/") :].lstrip("/")

        # If an absolute path was stored, try to map it back to uploads/.
        try:
            if os.path.isabs(fp):
                uploads_dir = os.path.abspath(_uploads_dir())
                fp_abs = os.path.abspath(fp)
                try:
                    if os.path.commonpath([fp_abs, uploads_dir]) == uploads_dir:
                        rel = os.path.relpath(fp_abs, uploads_dir).replace("\\", "/")
                        return rel.lstrip("/")
                except Exception:
                    pass
                # Last resort: assume basename lives under uploads/
                return os.path.basename(fp_abs).lstrip("/")
        except Exception:
            pass

        return fp.lstrip("/")

    fp = (file_path or "").strip()
    if not fp:
        return ""
    fp = fp.replace("\\", "/")
    if fp.startswith(("http://", "https://")):
        return fp
    if fp.startswith("/uploads/"):
        return fp
    rel = _normalize_upload_rel_path(fp)
    if not rel:
        return ""
    return f"/uploads/{rel}"


def _public_image_url_if_exists(file_path: str) -> str:
    """
    Like _public_image_url, but tries to avoid returning URLs for missing local files.

    This prevents clients from requesting stale uploads (which show as broken images).
    For historical deployments, some rows may include an extra "uploads/" prefix or
    files may have been stored under a nested "uploads/" folder. This function tries
    both layouts and returns the first URL that maps to an existing file.
    """
    def _normalize_upload_rel_path(fp: str) -> str:
        # Keep logic in sync with _public_image_url (duplicated intentionally to avoid refactors).
        fp = (fp or "").strip()
        if not fp:
            return ""
        fp = fp.replace("\\", "/")
        if fp.startswith(("http://", "https://", "//")):
            return ""
        low = fp.lower()
        idx = low.rfind("/uploads/")
        if idx >= 0:
            return fp[idx + len("/uploads/") :].lstrip("/")
        idx2 = low.rfind("uploads/")
        if idx2 >= 0:
            return fp[idx2 + len("uploads/") :].lstrip("/")
        try:
            if os.path.isabs(fp):
                uploads_dir = os.path.abspath(_uploads_dir())
                fp_abs = os.path.abspath(fp)
                try:
                    if os.path.commonpath([fp_abs, uploads_dir]) == uploads_dir:
                        rel = os.path.relpath(fp_abs, uploads_dir).replace("\\", "/")
                        return rel.lstrip("/")
                except Exception:
                    pass
                return os.path.basename(fp_abs).lstrip("/")
        except Exception:
            pass
        return fp.lstrip("/")

    fp = (file_path or "").strip()
    if not fp:
        return ""
    fp = fp.replace("\\", "/")
    if fp.startswith(("http://", "https://", "//")):
        return fp
    if fp.startswith("/uploads/"):
        # Public path stored in DB. We *can* still validate and also try the
        # historical nested "uploads/uploads" layout to prevent 404s.
        rel = fp[len("/uploads/") :].lstrip("/")
        if not rel:
            return ""
        uploads_dir = _uploads_dir()
        try:
            direct_path = os.path.join(uploads_dir, rel)
            if os.path.exists(direct_path):
                return f"/uploads/{rel}"
            nested = os.path.join(uploads_dir, "uploads", rel)
            if os.path.exists(nested):
                return f"/uploads/uploads/{rel}"
        except Exception:
            pass
        # If missing, omit instead of returning a broken URL.
        return ""

    rel = _normalize_upload_rel_path(fp)
    if not rel:
        return ""

    uploads_dir = _uploads_dir()
    try:
        direct_path = os.path.join(uploads_dir, rel)
        if os.path.exists(direct_path):
            return f"/uploads/{rel}"

        # Some deployments stored files under a nested "uploads/" folder.
        nested = os.path.join(uploads_dir, "uploads", rel)
        if os.path.exists(nested):
            return f"/uploads/uploads/{rel}"
    except Exception:
        pass

    # Fallback to legacy behavior (may 404 if the file is missing).
    return f"/uploads/{rel}"


def _locations_json_path() -> str:
    # Backend-owned location dataset (single source of truth).
    default = os.path.abspath(os.path.join(os.path.dirname(__file__), "locations.json"))
    return (os.environ.get("LOCATIONS_JSON_PATH") or default).strip() or default


@lru_cache(maxsize=1)
def _load_locations() -> dict[str, dict[str, list[str]]]:
    """
    Load State → District → Area dataset.
    Shape: { "Tamil Nadu": { "Chennai": ["Guindy", ...] } }
    """
    p = _locations_json_path()
    if not os.path.exists(p):
        raise HTTPException(status_code=503, detail=f"Location dataset missing at {p}")
    try:
        data = json.loads(open(p, "r", encoding="utf-8").read() or "{}")
    except Exception:
        raise HTTPException(status_code=503, detail="Failed to read location dataset")
    if not isinstance(data, dict) or not data:
        raise HTTPException(status_code=503, detail="Location dataset is empty")

    out: dict[str, dict[str, list[str]]] = {}
    for st, districts in data.items():
        if not isinstance(st, str) or not st.strip():
            continue
        if not isinstance(districts, dict):
            continue
        dd: dict[str, list[str]] = {}
        for d, areas in districts.items():
            if not isinstance(d, str) or not d.strip():
                continue
            if isinstance(areas, list):
                dd[d.strip()] = [str(a).strip() for a in areas if str(a).strip()]
            else:
                dd[d.strip()] = []
        if dd:
            out[st.strip()] = dd
    if not out:
        raise HTTPException(status_code=503, detail="Location dataset has no valid entries")
    return out


def _validate_location_selection(*, state: str, district: str, area: str) -> None:
    data = _load_locations()
    st = (state or "").strip()
    d = (district or "").strip()
    a = (area or "").strip()
    if not st or not d or not a:
        raise HTTPException(status_code=400, detail="State, District, and Area are required")
    if st not in data:
        raise HTTPException(status_code=400, detail="Invalid State")
    if d not in (data.get(st) or {}):
        raise HTTPException(status_code=400, detail="Invalid District for State")
    areas = (data.get(st) or {}).get(d) or []
    if a not in areas:
        raise HTTPException(status_code=400, detail="Invalid Area for State/District")


def _is_guest_account(u: User) -> bool:
    """
    Guest accounts are temporary users created via /auth/guest.
    They must not be allowed to publish ads.
    """
    email = (getattr(u, "email", "") or "").strip().lower()
    username = (getattr(u, "username", "") or "").strip().lower()
    return email.endswith("@guest.local") or username.startswith("guest_") or username.startswith("guest-")


def _safe_upload_ext(*, filename: str, content_type: str) -> str:
    fn = (filename or "").strip()
    ext = os.path.splitext(fn)[1].lower()
    if ext and len(ext) <= 12 and re.match(r"^\.[a-z0-9]+$", ext):
        return ext
    ct = (content_type or "").lower().strip()
    if ct in {"image/jpeg", "image/jpg"}:
        return ".jpg"
    if ct == "image/png":
        return ".png"
    if ct == "image/webp":
        return ".webp"
    if ct == "image/gif":
        return ".gif"
    if ct == "video/mp4":
        return ".mp4"
    if ct == "video/quicktime":
        return ".mov"
    # Safe generic fallback.
    return ".bin"


def _user_out(u: User) -> dict[str, Any]:
    img = (u.profile_image_path or "").strip()
    # Only expose an upload URL if the file actually exists. This prevents clients
    # from attempting to fetch stale/missing uploads (which leads to noisy 404s).
    img_url = ""
    if img:
        try:
            safe = img.lstrip("/").replace("\\", "/")
            # Cloudinary (or any remote) URL stored directly in DB.
            if safe.startswith(("http://", "https://", "//")):
                return {
                    "id": u.id,
                    "email": u.email,
                    "name": u.name,
                    "role": u.role,
                    "phone": u.phone,
                    "state": u.state,
                    "district": u.district,
                    "owner_category": u.owner_category,
                    "company_name": u.company_name,
                    "profile_image_url": img,
                }
            # Historical values might already include "uploads/".
            rel = safe[len("uploads/") :] if safe.startswith("uploads/") else safe
            disk_path = os.path.join(_uploads_dir(), rel)
            if os.path.exists(disk_path):
                img_url = _public_image_url(rel)
        except Exception:
            img_url = ""
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "role": u.role,
        "phone": u.phone,
        "state": u.state,
        "district": u.district,
        "owner_category": u.owner_category,
        "company_name": u.company_name,
        "profile_image_url": img_url,
    }


def _norm_key(s: str) -> str:
    """
    Normalize human-entered values for duplicate detection and strict matching.
    - lowercase
    - strip
    - replace non-alphanumeric with spaces
    - collapse whitespace
    """
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _norm_phone(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    # Keep digits; preserve a leading '+' if present.
    plus = s.startswith("+")
    digits = re.sub(r"[^0-9]", "", s)
    if not digits:
        return ""
    return f"+{digits}" if plus else digits


def _image_sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_AD_NUMBER_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def _base36(n: int) -> str:
    if n < 0:
        raise ValueError("base36 only supports non-negative integers")
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if n == 0:
        return "0"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = chars[r] + out
    return out


def _new_ad_number() -> str:
    """
    6-char uppercase alphanumeric, date-based prefix.

    Format: DDDDXX
    - DDDD: base36(days since 2020-01-01 UTC), left-padded to 4 chars
    - XX: 2 random base36 chars
    """
    today = dt.datetime.now(dt.timezone.utc).date()
    epoch = dt.date(2020, 1, 1)
    days = max(0, (today - epoch).days)
    day_part = _base36(days)[-4:].rjust(4, "0")
    rand_part = "".join(secrets.choice(_AD_NUMBER_ALPHABET) for _ in range(2))
    return f"{day_part}{rand_part}"


def _ensure_property_ad_number(db: Session) -> str:
    # Extremely low collision probability, but still enforce uniqueness at DB level.
    for _ in range(50):
        code = _new_ad_number()
        exists = db.execute(select(Property.id).where(Property.ad_number == code)).first()
        if not exists:
            return code
    # Fallback: if RNG keeps colliding (unlikely), fail deterministically.
    raise HTTPException(status_code=500, detail="Failed to allocate ad number")


def _log_moderation(
    db: Session,
    *,
    actor_user_id: int,
    entity_type: str,
    entity_id: int,
    action: str,
    reason: str = "",
) -> None:
    db.add(
        ModerationLog(
            actor_user_id=int(actor_user_id),
            entity_type=(entity_type or "").strip(),
            entity_id=int(entity_id),
            action=(action or "").strip(),
            reason=(reason or "").strip(),
        )
    )


os.makedirs(_uploads_dir(), exist_ok=True)


@app.get("/uploads/{path:path}", include_in_schema=False)
def uploads_proxy(path: str):
    """
    Serve locally-stored uploads from disk.

    Render (and other PaaS) environments often have ephemeral filesystems; older DB rows
    may reference files that no longer exist. To avoid noisy 404s in logs for these stale
    URLs, we return 204 when the file is missing.
    """
    rel = (path or "").lstrip("/").replace("\\", "/")
    if not rel:
        return Response(status_code=204)
    base = _uploads_dir()
    try:
        direct = os.path.join(base, rel)
        if os.path.exists(direct):
            return FileResponse(direct)
        nested = os.path.join(base, "uploads", rel)
        if os.path.exists(nested):
            return FileResponse(nested)
    except Exception:
        pass
    return Response(status_code=204)


@app.on_event("startup")
def seed_admin_user() -> None:
    """
    Create the default administrator account for GUI access:
    username: Admin
    password: Admin@123
    """
    try:
        with session_scope() as db:
            admin = db.execute(select(User).where(User.username == "Admin")).scalar_one_or_none()
            if admin:
                return
            admin = User(
                email="admin@local",
                username="Admin",
                name="Administrator",
                role="admin",
                password_hash=hash_password("Admin@123"),
            )
            db.add(admin)
            db.flush()
            db.add(Subscription(user_id=admin.id, status="active", provider="google_play"))
    except Exception:
        # If the DB isn't migrated yet, ignore and seed later.
        return


# -----------------------
# Dependencies
# -----------------------
def get_db():
    with session_scope() as db:
        yield db


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    if not authorization.lower().startswith("bearer "):
        return None
    return authorization.split(" ", 1)[1].strip() or None


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_access_token(token)
        user_id = int(payload.get("sub") or 0)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    # Treat suspended accounts as disabled (except admin).
    try:
        if (user.role or "").lower() != "admin" and (user.approval_status or "").lower() == "suspended":
            raise HTTPException(status_code=403, detail="Account disabled")
    except HTTPException:
        raise
    except Exception:
        pass
    return user


def get_optional_user(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> User | None:
    token = _bearer_token(authorization)
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        user_id = int(payload.get("sub") or 0)
    except Exception:
        return None
    if not user_id:
        return None
    return db.get(User, user_id)


# -----------------------
# Schemas
# -----------------------
class RegisterIn(BaseModel):
    email: str
    # We keep `username` for backward compatibility, but the mobile UI will use phone.
    # If `phone` is present, server will treat it as the primary identifier.
    username: str = ""
    phone: str = ""
    password: str = Field(min_length=6)
    name: str = ""
    state: str = ""
    district: str = ""
    role: str = "user"  # user | owner
    owner_category: str = ""  # required when role=owner (enforced softly)
    company_name: str = ""
    company_description: str = ""
    company_address: str = ""
    gender: str = ""  # legacy (old clients)


class LoginRequestOtpIn(BaseModel):
    identifier: str
    password: str


class LoginVerifyOtpIn(BaseModel):
    identifier: str
    password: str
    otp: str


class GoogleLoginIn(BaseModel):
    id_token: str = Field(..., min_length=1)


class ForgotRequestOtpIn(BaseModel):
    identifier: str


class ForgotResetIn(BaseModel):
    identifier: str
    otp: str
    new_password: str = Field(min_length=6)


class MeUpdateIn(BaseModel):
    name: str = ""


class ChangeEmailRequestIn(BaseModel):
    new_email: str


class ChangeEmailVerifyIn(BaseModel):
    new_email: str
    otp: str


class ChangePhoneRequestIn(BaseModel):
    new_phone: str


class ChangePhoneVerifyIn(BaseModel):
    new_phone: str
    otp: str


class PropertyCreateIn(BaseModel):
    title: str
    description: str = ""
    property_type: str = "apartment"
    rent_sale: str = "rent"
    price: int = 0
    # Backward compatibility: `location` is still accepted and used as a display string.
    location: str = ""
    # New: structured location filtering + normalized address duplication checks.
    state: str = ""
    district: str = ""
    area: str = ""
    address: str = ""
    amenities: list[str] = Field(default_factory=list)
    availability: str = "available"
    contact_phone: str = ""
    contact_email: str = ""
    # Optional: owner company name to display on ads.
    # This updates the owner's profile (User.company_name) when provided.
    company_name: str = ""
    gps_lat: float | None = None
    gps_lng: float | None = None


class PropertyUpdateIn(BaseModel):
    """
    Partial update for owner/admin editing an existing property.
    Only provided fields are updated.
    """

    title: str | None = None
    description: str | None = None
    property_type: str | None = None
    rent_sale: str | None = None
    price: int | None = None
    location: str | None = None
    state: str | None = None
    district: str | None = None
    area: str | None = None
    address: str | None = None
    amenities: list[str] | None = None
    availability: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    company_name: str | None = None
    gps_lat: float | None = None
    gps_lng: float | None = None


class ModerateIn(BaseModel):
    reason: str = ""


class AllowDuplicatesIn(BaseModel):
    allow_duplicate_address: bool | None = None
    allow_duplicate_phone: bool | None = None
    reason: str = ""


class AdminLoginIn(BaseModel):
    identifier: str
    password: str


# -----------------------
# Health
# -----------------------
@app.get("/health")
def health():
    return {"ok": True}


# -----------------------
# Metadata (categories)
# -----------------------
@app.get("/meta/categories")
def meta_categories() -> dict[str, Any]:
    """
    Single source of truth for:
    - `category` filters (customer browsing/search)
    - `owner_category` options (owner registration)

    Mobile/web clients can use `flat_items` for search UIs.
    """
    catalog, warning, source = _load_category_catalog()
    flat_items = _catalog_flat_items(catalog)
    return {
        "version": str(catalog.get("version") or ""),
        "updated": str(catalog.get("updated") or ""),
        "categories": catalog.get("categories") or [],
        # Owner categories are the same as selectable items.
        "owner_categories": [x.get("label") for x in flat_items if x.get("label")],
        "flat_items": flat_items,
        "source": source,
        "warning": warning,
    }


# -----------------------
# Locations (State/District/Area)
# -----------------------
@app.get("/locations/states")
def location_states() -> dict[str, Any]:
    data = _load_locations()
    states = sorted([s for s in data.keys() if s], key=lambda x: x.lower())
    return {"items": states}


@app.get("/locations/districts")
def location_districts(state: str = Query(..., min_length=1)) -> dict[str, Any]:
    st = (state or "").strip()
    data = _load_locations()
    districts = sorted(list((data.get(st) or {}).keys()), key=lambda x: x.lower())
    return {"items": districts}


@app.get("/locations/areas")
def location_areas(state: str = Query(..., min_length=1), district: str = Query(..., min_length=1)) -> dict[str, Any]:
    st = (state or "").strip()
    d = (district or "").strip()
    data = _load_locations()
    areas = (data.get(st) or {}).get(d) or []
    areas = sorted([a for a in areas if a], key=lambda x: x.lower())
    return {"items": areas}


# -----------------------
# Auth
# -----------------------
@app.post("/auth/register")
def register(data: RegisterIn, db: Annotated[Session, Depends(get_db)]):
    email = data.email.strip().lower()
    phone = (data.phone or "").strip()
    phone_norm = _norm_phone(phone)
    username = (phone or data.username or "").strip()
    role = (data.role or "user").strip().lower()
    owner_category = (data.owner_category or "").strip()
    company_name = (data.company_name or "").strip()
    company_name_norm = _norm_key(company_name)
    company_description = (data.company_description or "").strip()
    company_address = (data.company_address or "").strip()
    company_address_norm = _norm_key(company_address)
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email")
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Invalid username")
    if role not in {"user", "owner"}:
        raise HTTPException(status_code=400, detail="Invalid role")

    exists = db.execute(
        select(User).where(
            (User.email == email)
            | (User.username == username)
            | ((User.phone_normalized == phone_norm) & (User.phone_normalized != ""))
            | ((User.company_name_normalized == company_name_norm) & (User.company_name_normalized != ""))
        )
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="User already exists")

    approval_status = "pending" if role == "owner" else "approved"
    user = User(
        email=email,
        username=username,
        phone=phone,
        phone_normalized=phone_norm,
        name=(data.name or "").strip(),
        state=(data.state or "").strip(),
        district=(data.district or "").strip(),
        gender=(data.gender or "").strip(),
        role=role,
        owner_category=owner_category,
        company_name=company_name,
        company_name_normalized=company_name_norm,
        company_description=company_description,
        company_address=company_address,
        company_address_normalized=company_address_norm,
        approval_status=approval_status,
        password_hash=hash_password(data.password),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        # Even with the pre-check above, concurrent requests (or double-submits) can still
        # violate unique constraints. Convert to a deterministic 409 instead of a 500.
        db.rollback()
        raise HTTPException(status_code=409, detail="User already exists")
    # Ensure a subscription row exists.
    db.add(Subscription(user_id=user.id, status="inactive", provider="google_play"))
    return {"ok": True, "user_id": user.id}


@app.post("/auth/login/request-otp")
def login_request_otp(data: LoginRequestOtpIn, db: Annotated[Session, Depends(get_db)]):
    identifier = data.identifier.strip()
    phone_norm = _norm_phone(identifier)
    limiter.hit(key=f"otp:login:req:{identifier.lower()}", limit=5, window_seconds=10 * 60, detail="Too many OTP requests")
    user = db.execute(
        select(User).where(
            (User.email == identifier.lower())
            | (User.username == identifier)
            | (User.phone == identifier)
            | ((User.phone_normalized == phone_norm) & (User.phone_normalized != ""))
        )
    ).scalar_one_or_none()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=otp_exp_minutes())
    # Keep at most one active code per (identifier, purpose).
    db.execute(delete(OtpCode).where((OtpCode.identifier == identifier) & (OtpCode.purpose == "login")))
    db.add(OtpCode(identifier=identifier, purpose="login", code=code, expires_at=expires))
    try:
        to_email = user.email
        purpose = "login"
        if (user.role or "").lower() == "admin":
            to_email = _admin_otp_email()
            purpose = "admin_login"
        delivery = send_otp_email(to_email=to_email, otp=code, purpose=purpose)
    except EmailSendError as e:
        raise HTTPException(status_code=500, detail=str(e) or "Failed to send OTP")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to send OTP")
    if delivery == "console":
        return {"ok": True, "message": "OTP generated. Email service not configured; check server logs for the OTP."}
    if (user.role or "").lower() == "admin":
        return {"ok": True, "message": "OTP sent to admin mail."}
    return {"ok": True, "message": "OTP sent to your registered email."}


@app.post("/auth/login/verify-otp")
def login_verify_otp(data: LoginVerifyOtpIn, db: Annotated[Session, Depends(get_db)]):
    identifier = data.identifier.strip()
    phone_norm = _norm_phone(identifier)
    limiter.hit(key=f"otp:login:verify:{identifier.lower()}", limit=12, window_seconds=10 * 60, detail="Too many OTP attempts")
    user = db.execute(
        select(User).where(
            (User.email == identifier.lower())
            | (User.username == identifier)
            | (User.phone == identifier)
            | ((User.phone_normalized == phone_norm) & (User.phone_normalized != ""))
        )
    ).scalar_one_or_none()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    now = dt.datetime.now(dt.timezone.utc)
    otp = (
        db.execute(
            select(OtpCode)
            .where(
                (OtpCode.identifier == identifier)
                & (OtpCode.purpose == "login")
                & (OtpCode.code == data.otp.strip())
                & (OtpCode.expires_at > now)
            )
            .order_by(OtpCode.id.desc())
        )
        .scalars()
        .first()
    )
    if not otp:
        raise HTTPException(status_code=401, detail="Invalid OTP")
    # One-time: consume the OTP.
    db.execute(delete(OtpCode).where(OtpCode.id == otp.id))

    token = create_access_token(user_id=user.id, role=user.role)
    return {
        "access_token": token,
        "user": _user_out(user),
    }


@app.post("/auth/google")
def auth_google(data: GoogleLoginIn, db: Annotated[Session, Depends(get_db)]):
    """
    Google Sign-In:
    - Verify Google ID token signature/issuer
    - Enforce audience when GOOGLE_OAUTH_CLIENT_ID(S) is configured
    - Create (or reuse) a user by verified email
    - Issue a standard JWT access token
    """
    token_raw = (data.id_token or "").strip()
    if not token_raw:
        raise HTTPException(status_code=400, detail="Missing id_token")

    allowed_aud = google_oauth_client_ids()
    if app_env() in {"prod", "production"} and not allowed_aud:
        raise HTTPException(status_code=500, detail="Google Sign-In is not configured (missing GOOGLE_OAUTH_CLIENT_ID)")

    try:
        info = google_id_token.verify_oauth2_token(token_raw, google_auth_requests.Request())
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    aud = str(info.get("aud") or "")
    if allowed_aud and aud not in set(allowed_aud):
        raise HTTPException(status_code=401, detail="Google token audience mismatch")

    email = str(info.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=401, detail="Google token missing email")
    if info.get("email_verified") is False:
        raise HTTPException(status_code=401, detail="Google email is not verified")

    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user:
        # Create a new "user" role account for Google Sign-In.
        base = re.sub(r"[^a-zA-Z0-9_]+", "_", (email.split("@", 1)[0] or "user")).strip("_")
        base = base or "user"
        username = base
        # Ensure unique username.
        for _ in range(20):
            exists = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
            if not exists:
                break
            username = f"{base}_{secrets.randbelow(10_000)}"
        else:
            username = f"user_{secrets.token_hex(4)}"

        display_name = str(info.get("name") or info.get("given_name") or "").strip()
        user = User(
            email=email,
            username=username,
            phone="",
            phone_normalized="",
            name=display_name,
            state="",
            district="",
            gender="",
            role="user",
            owner_category="",
            company_name="",
            company_name_normalized="",
            company_description="",
            company_address="",
            company_address_normalized="",
            approval_status="approved",
            password_hash=hash_password(secrets.token_urlsafe(32)),
        )
        db.add(user)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="User already exists")
        db.add(Subscription(user_id=user.id, status="inactive", provider="google_play"))
    else:
        # Ensure a subscription row exists (older rows may be missing).
        sub = db.execute(select(Subscription).where(Subscription.user_id == user.id)).scalar_one_or_none()
        if not sub:
            db.add(Subscription(user_id=user.id, status="inactive", provider="google_play"))

    token = create_access_token(user_id=user.id, role=user.role)
    return {"access_token": token, "user": _user_out(user)}


@app.post("/auth/guest")
def guest(db: Annotated[Session, Depends(get_db)]):
    # Create a lightweight guest user.
    now = dt.datetime.now(dt.timezone.utc)
    email = f"guest-{int(now.timestamp())}@guest.local"
    username = f"guest_{int(now.timestamp())}"
    user = User(email=email, username=username, name="Guest", role="user", password_hash=hash_password("guest-unsafe"))
    db.add(user)
    db.flush()
    db.add(Subscription(user_id=user.id, status="inactive", provider="google_play"))
    token = create_access_token(user_id=user.id, role=user.role)
    return {
        "access_token": token,
        "user": _user_out(user),
    }


@app.post("/auth/forgot/request-otp")
def forgot_request_otp(data: ForgotRequestOtpIn, db: Annotated[Session, Depends(get_db)]):
    identifier = data.identifier.strip()
    phone_norm = _norm_phone(identifier)
    limiter.hit(key=f"otp:forgot:req:{identifier.lower()}", limit=5, window_seconds=10 * 60, detail="Too many OTP requests")
    user = db.execute(
        select(User).where(
            (User.email == identifier.lower())
            | (User.username == identifier)
            | (User.phone == identifier)
            | ((User.phone_normalized == phone_norm) & (User.phone_normalized != ""))
        )
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=otp_exp_minutes())
    db.execute(delete(OtpCode).where((OtpCode.identifier == identifier) & (OtpCode.purpose == "forgot")))
    db.add(OtpCode(identifier=identifier, purpose="forgot", code=code, expires_at=expires))
    try:
        delivery = send_otp_email(to_email=user.email, otp=code, purpose="forgot")
    except EmailSendError as e:
        raise HTTPException(status_code=500, detail=str(e) or "Failed to send OTP")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to send OTP")
    if delivery == "console":
        return {"ok": True, "message": "OTP generated. Email service not configured; check server logs for the OTP."}
    return {"ok": True, "message": "OTP sent to your registered email."}


@app.post("/auth/forgot/reset")
def forgot_reset(data: ForgotResetIn, db: Annotated[Session, Depends(get_db)]):
    identifier = data.identifier.strip()
    phone_norm = _norm_phone(identifier)
    limiter.hit(key=f"otp:forgot:reset:{identifier.lower()}", limit=10, window_seconds=10 * 60, detail="Too many reset attempts")
    user = db.execute(
        select(User).where(
            (User.email == identifier.lower())
            | (User.username == identifier)
            | (User.phone == identifier)
            | ((User.phone_normalized == phone_norm) & (User.phone_normalized != ""))
        )
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    now = dt.datetime.now(dt.timezone.utc)
    otp = (
        db.execute(
            select(OtpCode)
            .where(
                (OtpCode.identifier == identifier)
                & (OtpCode.purpose == "forgot")
                & (OtpCode.code == data.otp.strip())
                & (OtpCode.expires_at > now)
            )
            .order_by(OtpCode.id.desc())
        )
        .scalars()
        .first()
    )
    if not otp:
        raise HTTPException(status_code=401, detail="Invalid OTP")
    db.execute(delete(OtpCode).where(OtpCode.id == otp.id))
    user.password_hash = hash_password(data.new_password)
    db.add(user)
    return {"ok": True}


# -----------------------
# Subscription
# -----------------------
@app.get("/me/subscription")
def me_subscription(
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    sub = db.execute(select(Subscription).where(Subscription.user_id == me.id)).scalar_one_or_none()
    if not sub:
        sub = Subscription(user_id=me.id, status="inactive", provider="google_play")
        db.add(sub)
        db.flush()
    return {"status": sub.status, "provider": sub.provider, "expires_at": sub.expires_at}


class VerifyPurchaseIn(BaseModel):
    token: str = Field(..., min_length=1)
    product_id: str | None = None


@app.post("/verify-purchase")
def verify_purchase(
    data: VerifyPurchaseIn,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Backward-compatible alias for subscription verification."""
    return verify_subscription(data, me=me, db=db)


class VerifySubscriptionIn(BaseModel):
    purchase_token: str = Field(..., min_length=1)
    product_id: str = Field(..., min_length=1)


def _ensure_plans(db: Session) -> None:
    """
    Ensure the four plans exist. This is idempotent.
    """
    def _env_int(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name) or default)
        except Exception:
            return int(default)

    plans = [
        ("aggressive_10", "Aggressive", 10, 30, 10),
        ("instant_79", "Instant", _env_int("SUBSCRIPTION_PRICE_INSTANT_INR", 79), 30, 50),
        ("smart_monthly_199", "Smart", _env_int("SUBSCRIPTION_PRICE_SMART_INR", 199), 30, 200),
        ("business_quarterly_499", "Business", _env_int("SUBSCRIPTION_PRICE_BUSINESS_INR", 499), 90, 1000),
    ]
    for pid, name, price, days, limit in plans:
        rec = db.get(SubscriptionPlan, pid)
        if not rec:
            db.add(SubscriptionPlan(id=pid, name=name, price_inr=price, duration_days=days, contact_limit=limit))
        else:
            rec.name = name
            rec.price_inr = int(price)
            rec.duration_days = int(days)
            rec.contact_limit = int(limit)
            db.add(rec)


@app.post("/verify-subscription")
def verify_subscription(
    data: VerifySubscriptionIn,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Validates a Google Play subscription purchase token.

    - If Google Play API credentials are configured, it performs real server-side validation.
    - Otherwise, it falls back to a dev-mode activation (keeps current environments working).
    """
    limiter.hit(key=f"sub:verify:{me.id}", limit=20, window_seconds=10 * 60, detail="Too many verification attempts")
    _ensure_plans(db)
    product_id = (data.product_id or "").strip()
    token = (data.purchase_token or "").strip()
    plan = db.get(SubscriptionPlan, product_id)
    if not plan:
        raise HTTPException(status_code=400, detail="Unknown product_id")

    # Idempotency / abuse prevention: purchase tokens must be unique.
    existing_token = db.execute(select(UserSubscription).where(UserSubscription.purchase_token == token)).scalar_one_or_none()
    if existing_token and int(existing_token.user_id) != int(me.id):
        raise HTTPException(status_code=409, detail="Purchase token already used by another account")

    now = dt.datetime.now(dt.timezone.utc)

    # Validate with Google Play when configured.
    expiry_dt: dt.datetime | None = None
    order_id: str | None = None
    try:
        result = verify_subscription_with_google_play(purchase_token=token, product_id=product_id)
        # paymentState==1 indicates payment received for subscriptions (for some purchase types).
        payment_state = result.get("paymentState")
        if payment_state is not None and int(payment_state) != 1:
            raise HTTPException(status_code=400, detail="Payment not completed")
        expiry_ms = result.get("expiryTimeMillis")
        if expiry_ms:
            expiry_dt = dt.datetime.fromtimestamp(int(expiry_ms) / 1000.0, tz=dt.timezone.utc)
        order_id = result.get("orderId")
    except GooglePlayNotConfigured:
        # Dev fallback: expire by plan duration.
        expiry_dt = now + dt.timedelta(days=int(plan.duration_days or 30))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not expiry_dt:
        expiry_dt = now + dt.timedelta(days=int(plan.duration_days or 30))

    # Upsert into legacy Subscription table (existing app logic).
    sub = db.execute(select(Subscription).where(Subscription.user_id == me.id)).scalar_one_or_none()
    if not sub:
        sub = Subscription(user_id=me.id, status="inactive", provider="google_play")
        db.add(sub)
        db.flush()
    sub.status = "active"
    sub.provider = "google_play"
    sub.purchase_token = token
    sub.expires_at = expiry_dt
    sub.updated_at = now
    db.add(sub)

    # Deactivate previous user_subscriptions for this user.
    db.execute(sa_update(UserSubscription).where(UserSubscription.user_id == me.id).values(active=False))

    us = UserSubscription(
        user_id=me.id,
        plan_id=plan.id,
        purchase_token=token,
        start_time=now,
        end_time=expiry_dt,
        active=True,
    )
    db.add(us)
    db.flush()

    return {
        "status": "valid",
        "expiry_time": int(expiry_dt.timestamp() * 1000),
        "order_id": order_id,
        "subscription": {"status": sub.status, "expires_at": sub.expires_at, "product_id": product_id},
    }
    sub = db.execute(select(Subscription).where(Subscription.user_id == me.id)).scalar_one_or_none()
    if not sub:
        sub = Subscription(user_id=me.id, status="inactive", provider="google_play")
        db.add(sub)
        db.flush()

    now = dt.datetime.now(dt.timezone.utc)
    product_id = (data.product_id or "").strip()
    # Default to monthly unless explicitly quarterly.
    days = 30
    if product_id == "business_quarterly_499":
        days = 90
    sub.status = "active"
    sub.provider = "google_play"
    sub.purchase_token = data.token.strip()
    sub.expires_at = now + dt.timedelta(days=days)
    sub.updated_at = now
    db.add(sub)
    return {"status": "valid", "subscription": {"status": sub.status, "expires_at": sub.expires_at, "product_id": product_id}}


@app.get("/me")
def me_profile(me: Annotated[User, Depends(get_current_user)]) -> dict[str, Any]:
    return {"user": _user_out(me)}


@app.patch("/me")
def me_update(
    data: MeUpdateIn,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    me.name = (data.name or "").strip()
    db.add(me)
    return {"ok": True, "user": _user_out(me)}


@app.post("/me/profile-image")
def me_upload_profile_image(
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
) -> dict[str, Any]:
    content_type = (file.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image uploads are allowed")

    try:
        raw = file.file.read()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid upload")
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload")
    _raise_if_too_large(size_bytes=len(raw), max_bytes=_max_upload_image_bytes())

    # AI moderation (reject before any storage).
    mod = _openai_moderate_image(raw=raw)
    if bool(mod.get("flagged")):
        _log_moderation(
            db,
            actor_user_id=me.id,
            entity_type="user_profile_media_upload",
            entity_id=int(me.id),
            action="reject",
            reason=f"Unsafe media rejected by AI moderation ({mod.get('summary')})",
        )
        raise HTTPException(status_code=400, detail="Unsafe media detected. Upload rejected.")

    stored_ext = _safe_upload_ext(filename=(file.filename or ""), content_type=content_type)
    token = secrets.token_hex(8)
    safe_name = f"u{me.id}_{token}{stored_ext}"

    # If Cloudinary is configured, store remotely and keep DB as a URL.
    if cloudinary_enabled():
        # Best-effort cleanup of previous profile image.
        try:
            if (me.profile_image_cloudinary_public_id or "").strip():
                cloudinary_destroy(public_id=me.profile_image_cloudinary_public_id, resource_type="image")
        except Exception:
            pass
        try:
            url, pid = cloudinary_upload_bytes(
                raw=raw,
                resource_type="image",
                public_id=f"user_profile_{me.id}_{token}",
                filename=(file.filename or "").strip() or safe_name,
                content_type=content_type,
            )
        except Exception as e:
            logger.exception("Cloudinary upload failed (profile image) user_id=%s filename=%r content_type=%r", me.id, file.filename, content_type)
            msg = str(e) or "Cloudinary upload failed"
            raise HTTPException(status_code=500, detail=f"Failed to upload to Cloudinary: {msg[:200]}")
        me.profile_image_path = url
        me.profile_image_cloudinary_public_id = pid
    else:
        disk_path = os.path.join(_uploads_dir(), safe_name)
        try:
            with open(disk_path, "wb") as out:
                out.write(raw)
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to save upload")
        me.profile_image_path = safe_name
        me.profile_image_cloudinary_public_id = ""
    db.add(me)
    return {"ok": True, "user": _user_out(me)}


@app.post("/me/change-email/request-otp")
def me_change_email_request_otp(
    data: ChangeEmailRequestIn,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    new_email = (data.new_email or "").strip().lower()
    limiter.hit(key=f"otp:change_email:req:{me.id}", limit=5, window_seconds=10 * 60, detail="Too many OTP requests")
    if not new_email or "@" not in new_email:
        raise HTTPException(status_code=400, detail="Invalid email")
    if new_email == (me.email or "").lower():
        raise HTTPException(status_code=400, detail="Email is unchanged")

    exists = db.execute(select(User.id).where((User.email == new_email) & (User.id != me.id))).first()
    if exists:
        raise HTTPException(status_code=409, detail="Email already in use")

    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=otp_exp_minutes())
    otp_identifier = f"email:{me.id}:{new_email}"
    db.execute(delete(OtpCode).where((OtpCode.identifier == otp_identifier) & (OtpCode.purpose == "change_email")))
    db.add(OtpCode(identifier=otp_identifier, purpose="change_email", code=code, expires_at=expires))
    try:
        delivery = send_otp_email(to_email=new_email, otp=code, purpose="change_email")
    except EmailSendError as e:
        raise HTTPException(status_code=500, detail=str(e) or "Failed to send OTP")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to send OTP")
    if delivery == "console":
        return {"ok": True, "message": "OTP generated. Email service not configured; check server logs for the OTP."}
    return {"ok": True, "message": "OTP sent to your new email."}


@app.post("/me/change-email/verify")
def me_change_email_verify(
    data: ChangeEmailVerifyIn,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    new_email = (data.new_email or "").strip().lower()
    otp = (data.otp or "").strip()
    limiter.hit(key=f"otp:change_email:verify:{me.id}", limit=12, window_seconds=10 * 60, detail="Too many OTP attempts")
    if not new_email or "@" not in new_email:
        raise HTTPException(status_code=400, detail="Invalid email")
    if not otp:
        raise HTTPException(status_code=400, detail="OTP required")

    exists = db.execute(select(User.id).where((User.email == new_email) & (User.id != me.id))).first()
    if exists:
        raise HTTPException(status_code=409, detail="Email already in use")

    otp_identifier = f"email:{me.id}:{new_email}"
    now = dt.datetime.now(dt.timezone.utc)
    rec = (
        db.execute(
            select(OtpCode)
            .where(
                (OtpCode.identifier == otp_identifier)
                & (OtpCode.purpose == "change_email")
                & (OtpCode.code == otp)
                & (OtpCode.expires_at > now)
            )
            .order_by(OtpCode.id.desc())
        )
        .scalars()
        .first()
    )
    if not rec:
        raise HTTPException(status_code=401, detail="Invalid OTP")
    db.execute(delete(OtpCode).where(OtpCode.id == rec.id))

    me.email = new_email
    db.add(me)
    return {"ok": True, "user": _user_out(me)}


@app.post("/me/change-phone/request-otp")
def me_change_phone_request_otp(
    data: ChangePhoneRequestIn,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    new_phone = (data.new_phone or "").strip()
    limiter.hit(key=f"otp:change_phone:req:{me.id}", limit=5, window_seconds=10 * 60, detail="Too many OTP requests")
    phone_norm = _norm_phone(new_phone)
    if not phone_norm or len(re.sub(r"[^0-9]", "", phone_norm)) < 6:
        raise HTTPException(status_code=400, detail="Invalid phone")
    if phone_norm == _norm_phone(me.phone or ""):
        raise HTTPException(status_code=400, detail="Phone is unchanged")

    exists = db.execute(
        select(User.id).where((User.phone_normalized == phone_norm) & (User.phone_normalized != "") & (User.id != me.id))
    ).first()
    if exists:
        raise HTTPException(status_code=409, detail="Phone already in use")

    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=otp_exp_minutes())
    otp_identifier = f"phone:{me.id}:{phone_norm}"
    db.execute(delete(OtpCode).where((OtpCode.identifier == otp_identifier) & (OtpCode.purpose == "change_phone")))
    db.add(OtpCode(identifier=otp_identifier, purpose="change_phone", code=code, expires_at=expires))
    try:
        delivery = send_otp_email(to_email=me.email, otp=code, purpose=f"change_phone:{phone_norm}")
    except EmailSendError as e:
        raise HTTPException(status_code=500, detail=str(e) or "Failed to send OTP")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to send OTP")
    if delivery == "console":
        return {"ok": True, "message": "OTP generated. Email service not configured; check server logs for the OTP."}
    return {"ok": True, "message": "OTP sent to your registered email."}


@app.post("/me/change-phone/verify")
def me_change_phone_verify(
    data: ChangePhoneVerifyIn,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    new_phone = (data.new_phone or "").strip()
    otp = (data.otp or "").strip()
    limiter.hit(key=f"otp:change_phone:verify:{me.id}", limit=12, window_seconds=10 * 60, detail="Too many OTP attempts")
    phone_norm = _norm_phone(new_phone)
    if not phone_norm:
        raise HTTPException(status_code=400, detail="Invalid phone")
    if not otp:
        raise HTTPException(status_code=400, detail="OTP required")

    exists = db.execute(
        select(User.id).where((User.phone_normalized == phone_norm) & (User.phone_normalized != "") & (User.id != me.id))
    ).first()
    if exists:
        raise HTTPException(status_code=409, detail="Phone already in use")

    otp_identifier = f"phone:{me.id}:{phone_norm}"
    now = dt.datetime.now(dt.timezone.utc)
    rec = (
        db.execute(
            select(OtpCode)
            .where(
                (OtpCode.identifier == otp_identifier)
                & (OtpCode.purpose == "change_phone")
                & (OtpCode.code == otp)
                & (OtpCode.expires_at > now)
            )
            .order_by(OtpCode.id.desc())
        )
        .scalars()
        .first()
    )
    if not rec:
        raise HTTPException(status_code=401, detail="Invalid OTP")
    db.execute(delete(OtpCode).where(OtpCode.id == rec.id))

    me.phone = new_phone
    me.phone_normalized = phone_norm
    db.add(me)
    return {"ok": True, "user": _user_out(me)}


@app.delete("/me")
def me_delete(
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    if (me.role or "").lower() == "admin":
        raise HTTPException(status_code=403, detail="Admin account cannot be deleted")

    prop_ids = [int(x) for x in db.execute(select(Property.id).where(Property.owner_id == me.id)).scalars().all()]
    if prop_ids:
        # Delete dependent rows first to avoid FK errors (e.g. contact usage referencing properties).
        db.execute(delete(FreeContactUsage).where(FreeContactUsage.property_id.in_(prop_ids)))
        db.execute(delete(ContactUsage).where(ContactUsage.property_id.in_(prop_ids)))
        db.execute(delete(SavedProperty).where(SavedProperty.property_id.in_(prop_ids)))
        db.execute(delete(PropertyImage).where(PropertyImage.property_id.in_(prop_ids)))
        db.execute(delete(Property).where(Property.id.in_(prop_ids)))

    db.execute(delete(SavedProperty).where(SavedProperty.user_id == me.id))
    db.execute(delete(Subscription).where(Subscription.user_id == me.id))
    db.execute(delete(User).where(User.id == me.id))
    return {"ok": True}


# -----------------------
# Properties (browse is free; contact is subscription-gated)
# -----------------------
def _property_out(
    p: Property,
    *,
    owner: User | None = None,
    include_unapproved_images: bool = False,
    include_internal: bool = False,
) -> dict[str, Any]:
    try:
        amenities = json.loads(p.amenities_json or "[]") if p.amenities_json else []
    except Exception:
        amenities = []
    images = []
    try:
        for i in sorted((p.images or []), key=lambda x: (int(getattr(x, "sort_order", 0) or 0), int(getattr(x, "id", 0) or 0))):
            if not include_unapproved_images and (i.status or "") != "approved":
                continue
            url = _public_image_url_if_exists(i.file_path)
            if not url:
                continue
            img_out: dict[str, Any] = {
                "id": i.id,
                "url": url,
                "sort_order": i.sort_order,
                "content_type": (i.content_type or "").strip(),
                "size_bytes": int(i.size_bytes or 0),
            }
            if include_internal:
                img_out["status"] = i.status
                img_out["image_hash"] = i.image_hash
            images.append(img_out)
    except Exception:
        images = []
    location_display = (p.area or "").strip() or p.address or p.location
    o = owner or getattr(p, "owner", None)
    owner_name = (getattr(o, "name", "") or "").strip() if o else ""
    owner_company_name = (getattr(o, "company_name", "") or "").strip() if o else ""
    owner_username = (getattr(o, "username", "") or "").strip() if o else ""
    owner_email = (getattr(o, "email", "") or "").strip() if o else ""
    owner_phone = (getattr(o, "phone", "") or "").strip() if o else ""
    adv_number = (getattr(p, "ad_number", "") or "").strip() or str(p.id)
    out: dict[str, Any] = {
        "id": p.id,
        "adv_number": adv_number,
        "title": p.title,
        "description": p.description,
        "property_type": p.property_type,
        "rent_sale": p.rent_sale,
        "price": p.price,
        "price_display": f"{p.price:,}",
        "location": p.location,
        "location_display": location_display,
        "state": p.state,
        "district": p.district,
        "area": getattr(p, "area", "") or "",
        "amenities": amenities,
        "availability": p.availability,
        "status": p.status,
        "images": images,
        "created_at": p.created_at.isoformat() if getattr(p, "created_at", None) else "",
        "owner_name": owner_name,
        "owner_company_name": owner_company_name,
    }
    if include_internal:
        out["owner_id"] = int(p.owner_id)
        out["owner_username"] = owner_username
        out["owner_email"] = owner_email
        out["owner_phone"] = owner_phone
        out["contact_phone"] = (p.contact_phone or "").strip()
        out["contact_email"] = (p.contact_email or "").strip()
        out["gps_lat"] = getattr(p, "gps_lat", None)
        out["gps_lng"] = getattr(p, "gps_lng", None)
        out["moderation_reason"] = p.moderation_reason
        out["address"] = p.address
        out["address_normalized"] = p.address_normalized
        out["contact_phone_normalized"] = p.contact_phone_normalized
        out["state_normalized"] = p.state_normalized
        out["district_normalized"] = p.district_normalized
        out["area_normalized"] = getattr(p, "area_normalized", "") or ""
        out["allow_duplicate_address"] = p.allow_duplicate_address
        out["allow_duplicate_phone"] = p.allow_duplicate_phone
    return out


def _contacted_property_ids(db: Session, user_id: int | None, property_ids: list[int]) -> set[int]:
    if not user_id:
        return set()
    ids = [int(x) for x in property_ids if int(x) > 0]
    if not ids:
        return set()
    free_ids = db.execute(
        select(FreeContactUsage.property_id).where(
            (FreeContactUsage.user_id == int(user_id)) & (FreeContactUsage.property_id.in_(ids))
        )
    ).scalars().all()
    paid_ids = db.execute(
        select(ContactUsage.property_id).where(
            (ContactUsage.user_id == int(user_id)) & (ContactUsage.property_id.in_(ids))
        )
    ).scalars().all()
    return set(int(x) for x in free_ids) | set(int(x) for x in paid_ids)


def _apply_contacted_flags(db: Session, me: User | None, items: list[dict[str, Any]]) -> None:
    if not me or not items:
        return
    ids = [int(x.get("id") or 0) for x in items if int(x.get("id") or 0) > 0]
    if not ids:
        return
    contacted = _contacted_property_ids(db, me.id, ids)
    for item in items:
        pid = int(item.get("id") or 0)
        if pid > 0:
            item["contacted"] = pid in contacted


def _split_csv_values(v: str | None) -> list[str]:
    """
    Parse a comma-separated query param into a clean list.
    Used for multi-select filters (e.g. area=a,b,c).
    """
    raw = (v or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(",")]
    return [p for p in parts if p]


@app.get("/properties")
def list_properties(
    db: Annotated[Session, Depends(get_db)],
    me: Annotated[User | None, Depends(get_optional_user)],
    q: str | None = Query(default=None),
    rent_sale: str | None = Query(default=None),
    property_type: str | None = Query(default=None),
    max_price: int | None = Query(default=None),
    state: str | None = Query(default=None),
    district: str | None = Query(default=None),
    area: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    sort_budget: str | None = Query(default=None),  # top|bottom|asc|desc
    posted_within_days: int | None = Query(default=None, ge=1, le=365),
):
    state_in = (state or "").strip()
    district_in = (district or "").strip()
    area_in = (area or "").strip()
    state_norm = _norm_key(state_in)
    district_norm = _norm_key(district_in)
    area_list = _split_csv_values(area_in)
    area_norms = [_norm_key(x) for x in area_list]
    area_norms = [x for x in area_norms if x]
    area_norm = _norm_key(area_in)

    # Only approved listings from approved (non-suspended) owners are visible.
    stmt = (
        select(Property, User)
        .options(selectinload(Property.images))
        .join(User, Property.owner_id == User.id)
        .where((Property.status == "approved") & (User.approval_status == "approved"))
    )
    sb = (sort_budget or "").strip().lower()
    if sb in {"top", "desc", "high"}:
        stmt = stmt.order_by(Property.price.desc(), Property.id.desc())
    elif sb in {"bottom", "asc", "low"}:
        stmt = stmt.order_by(Property.price.asc(), Property.id.desc())
    else:
        stmt = stmt.order_by(Property.id.desc())
    if state_norm:
        stmt = stmt.where(Property.state_normalized == state_norm)
    if district_norm:
        stmt = stmt.where(Property.district_normalized == district_norm)
    if area_norms:
        stmt = stmt.where(Property.area_normalized.in_(area_norms))
    elif area_norm:
        stmt = stmt.where(Property.area_normalized == area_norm)
    if q:
        q_like = f"%{q.strip()}%"
        stmt = stmt.where((Property.title.ilike(q_like)) | (Property.location.ilike(q_like)))
    if rent_sale:
        stmt = stmt.where(Property.rent_sale == rent_sale)
    if property_type:
        stmt = stmt.where(Property.property_type == property_type)
    if max_price is not None:
        stmt = stmt.where(Property.price <= int(max_price))

    if posted_within_days:
        now = dt.datetime.now(dt.timezone.utc)
        stmt = stmt.where(Property.created_at >= (now - dt.timedelta(days=int(posted_within_days))))

    rows = db.execute(stmt.limit(int(limit))).all()
    user_lat = None
    user_lon = None
    if me and _is_valid_gps(getattr(me, "gps_lat", None), getattr(me, "gps_lng", None)):
        user_lat = float(me.gps_lat)
        user_lon = float(me.gps_lng)
    items: list[dict[str, Any]] = []
    for (p, u) in rows:
        item = _property_out(p, owner=u)
        if user_lat is not None and user_lon is not None:
            try:
                if p.gps_lat is not None and p.gps_lng is not None:
                    dkm = _haversine_km(float(user_lat), float(user_lon), float(p.gps_lat), float(p.gps_lng))
                    item["distance_km"] = round(float(dkm), 3)
            except Exception:
                pass
        items.append(item)
    _apply_contacted_flags(db, me, items)
    # Seed demo data on first-ever run (only if the *table* is empty).
    #
    # NOTE: We must NOT seed based on "no results" for a specific filter, otherwise any
    # empty search would try to insert the same demo addresses again and trip the
    # partial unique indexes (e.g. uq_properties_address_normalized_no_override).
    if not items:
        has_any_property = db.execute(select(Property.id).limit(1)).first() is not None
        if not has_any_property:
            try:
                demo_owner = db.execute(select(User).where(User.username == "demo_owner")).scalar_one_or_none()
                if not demo_owner:
                    demo_owner = User(
                        email="owner@demo.local",
                        username="demo_owner",
                        name="Demo Owner",
                        role="owner",
                        password_hash=hash_password("password123"),
                        approval_status="approved",
                    )
                    db.add(demo_owner)
                    db.flush()

                # Ensure the demo owner has a subscription row (mobile/web expects it).
                sub = db.execute(select(Subscription).where(Subscription.user_id == demo_owner.id)).scalar_one_or_none()
                if not sub:
                    db.add(Subscription(user_id=demo_owner.id, status="inactive", provider="google_play"))

                p1 = Property(
                    owner_id=demo_owner.id,
                    title="Modern Studio Near Metro",
                    description="Bright studio with balcony.",
                    property_type="studio",
                    rent_sale="rent",
                    price=1200,
                    location="Downtown",
                    state="Karnataka",
                    district="Bengaluru (Bangalore) Urban",
                    area="Downtown",
                    state_normalized=_norm_key("Karnataka"),
                    district_normalized=_norm_key("Bengaluru (Bangalore) Urban"),
                    area_normalized=_norm_key("Downtown"),
                    address="Downtown",
                    address_normalized=_norm_key("Downtown"),
                    amenities_json='["wifi","parking","gym"]',
                    status="approved",
                    contact_phone="+1 555 0100",
                    contact_email="owner@demo.local",
                    contact_phone_normalized=_norm_phone("+1 555 0100"),
                    gps_lat=12.9716,
                    gps_lng=77.5946,
                )
                p2 = Property(
                    owner_id=demo_owner.id,
                    title="Family House With Garden",
                    description="3BR house, quiet neighborhood.",
                    property_type="house",
                    rent_sale="sale",
                    price=250000,
                    location="Greenwood",
                    state="Karnataka",
                    district="Bengaluru (Bangalore) Urban",
                    area="Greenwood",
                    state_normalized=_norm_key("Karnataka"),
                    district_normalized=_norm_key("Bengaluru (Bangalore) Urban"),
                    area_normalized=_norm_key("Greenwood"),
                    address="Greenwood",
                    address_normalized=_norm_key("Greenwood"),
                    amenities_json='["garden","parking"]',
                    status="approved",
                    contact_phone="+1 555 0200",
                    contact_email="owner@demo.local",
                    contact_phone_normalized=_norm_phone("+1 555 0200"),
                    gps_lat=12.9760,
                    gps_lng=77.6030,
                )
                db.add_all([p1, p2])
                db.flush()
            except IntegrityError:
                # If two first-time requests race, one may violate unique indexes.
                # Roll back the failed insert attempt and proceed with the normal query.
                db.rollback()

            # Only return demo results if they match the requested filter.
            rows = db.execute(stmt).all()
            items = []
            for (p, u) in rows:
                item = _property_out(p, owner=u)
                if user_lat is not None and user_lon is not None:
                    try:
                        if p.gps_lat is not None and p.gps_lng is not None:
                            dkm = _haversine_km(float(user_lat), float(user_lon), float(p.gps_lat), float(p.gps_lng))
                            item["distance_km"] = round(float(dkm), 3)
                    except Exception:
                        pass
                items.append(item)
            _apply_contacted_flags(db, me, items)

    return {"items": items}


@app.get("/properties/{property_id:int}")
def get_property(
    property_id: int,
    db: Annotated[Session, Depends(get_db)],
    me: Annotated[User | None, Depends(get_optional_user)],
):
    p = db.execute(select(Property).options(selectinload(Property.images)).where(Property.id == int(property_id))).scalar_one_or_none()
    if not p or p.status != "approved":
        raise HTTPException(status_code=404, detail="Property not found")
    owner = db.get(User, int(p.owner_id))
    if not owner or owner.approval_status != "approved":
        raise HTTPException(status_code=404, detail="Property not found")
    out = _property_out(p, owner=owner)
    _apply_contacted_flags(db, me, [out])
    return out


def _is_valid_gps(lat: float | None, lon: float | None) -> bool:
    try:
        if lat is None or lon is None:
            return False
        lat_f = float(lat)
        lon_f = float(lon)
        if not math.isfinite(lat_f) or not math.isfinite(lon_f):
            return False
        if abs(lat_f) < 1e-6 and abs(lon_f) < 1e-6:
            return False
        if abs(lat_f) > 90 or abs(lon_f) > 180:
            return False
        return True
    except Exception:
        return False


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * (math.sin(dlon / 2) ** 2)
    c = 2 * math.asin(math.sqrt(a))
    return r * c


@app.get("/properties/nearby")
def list_nearby_properties(
    db: Annotated[Session, Depends(get_db)],
    me: Annotated[User | None, Depends(get_optional_user)],
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(default=20.0, gt=0, le=500),
    limit: int = Query(default=20, ge=1, le=200),
    district: str | None = Query(default=None),
    state: str | None = Query(default=None),
    area: str | None = Query(default=None),
    q: str | None = Query(default=None),
    rent_sale: str | None = Query(default=None),
    property_type: str | None = Query(default=None),
    max_price: int | None = Query(default=None),
    posted_within_days: int | None = Query(default=None, ge=1, le=365),
):
    """
    Nearby ads using GPS proximity (Haversine). No external map APIs.
    Optional filters by District/State/Area (validated at creation time).

    Optimized approach:
    - Bounding-box prefilter on lat/lon
    - Distance calculation for ordering
    """
    district_norm = _norm_key((district or "").strip())
    state_norm = _norm_key((state or "").strip())
    area_in = (area or "").strip()
    area_list = _split_csv_values(area_in)
    area_norms = [_norm_key(x) for x in area_list]
    area_norms = [x for x in area_norms if x]
    area_norm = _norm_key(area_in)

    if me and _is_valid_gps(lat, lon):
        me.gps_lat = float(lat)
        me.gps_lng = float(lon)
        db.add(me)

    # Bounding box (fast prefilter).
    lat_delta = float(radius_km) / 111.0
    cos_lat = math.cos(math.radians(float(lat))) or 1e-9
    lon_delta = float(radius_km) / (111.0 * cos_lat)
    min_lat, max_lat = float(lat) - lat_delta, float(lat) + lat_delta
    min_lon, max_lon = float(lon) - lon_delta, float(lon) + lon_delta

    stmt = (
        select(Property, User)
        .options(selectinload(Property.images))
        .join(User, Property.owner_id == User.id)
        .where((Property.status == "approved") & (User.approval_status == "approved"))
        .where(Property.gps_lat.is_not(None))
        .where(Property.gps_lng.is_not(None))
        .where((Property.gps_lat >= min_lat) & (Property.gps_lat <= max_lat))
        .where((Property.gps_lng >= min_lon) & (Property.gps_lng <= max_lon))
    )

    if district_norm:
        stmt = stmt.where(Property.district_normalized == district_norm)
    if state_norm:
        stmt = stmt.where(Property.state_normalized == state_norm)
    if area_norms:
        stmt = stmt.where(Property.area_normalized.in_(area_norms))
    elif area_norm:
        stmt = stmt.where(Property.area_normalized == area_norm)

    if q:
        q_like = f"%{q.strip()}%"
        stmt = stmt.where((Property.title.ilike(q_like)) | (Property.location.ilike(q_like)))
    if rent_sale:
        stmt = stmt.where(Property.rent_sale == rent_sale)
    if property_type:
        stmt = stmt.where(Property.property_type == property_type)
    if max_price is not None:
        stmt = stmt.where(Property.price <= int(max_price))
    if posted_within_days:
        now = dt.datetime.now(dt.timezone.utc)
        stmt = stmt.where(Property.created_at >= (now - dt.timedelta(days=int(posted_within_days))))

    # Postgres can compute distance in SQL for correct ordering; SQLite fallback computes in Python.
    dialect = getattr(getattr(db, "bind", None), "dialect", None)
    dname = getattr(dialect, "name", "") if dialect else ""

    if dname == "postgresql":
        # Haversine in SQL (meters/km) + ORDER BY distance for true nearest results.
        lat1 = func.radians(float(lat))
        lon1 = func.radians(float(lon))
        lat2 = func.radians(Property.gps_lat)
        lon2 = func.radians(Property.gps_lng)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = func.pow(func.sin(dlat / 2.0), 2) + func.cos(lat1) * func.cos(lat2) * func.pow(func.sin(dlon / 2.0), 2)
        c = 2.0 * func.asin(func.sqrt(a))
        dist_km = (6371.0 * c).label("distance_km")

        stmt2 = stmt.add_columns(dist_km).order_by(dist_km.asc(), Property.id.desc()).limit(int(limit))
        rows2 = db.execute(stmt2).all()
        items2: list[dict[str, Any]] = []
        for (p, u, dkm) in rows2:
            if dkm is None:
                continue
            if float(dkm) <= float(radius_km):
                item = _property_out(p, owner=u)
                item["distance_km"] = round(float(dkm), 3)
                items2.append(item)
        _apply_contacted_flags(db, me, items2)
        return {"items": items2}

    rows = db.execute(stmt.limit(int(limit) * 5)).all()
    out_items: list[dict[str, Any]] = []
    for (p, u) in rows:
        dkm = _haversine_km(float(lat), float(lon), float(p.gps_lat or 0), float(p.gps_lng or 0))
        if dkm <= float(radius_km):
            item = _property_out(p, owner=u)
            item["distance_km"] = round(float(dkm), 3)
            out_items.append(item)

    out_items.sort(key=lambda x: (float(x.get("distance_km") or 9e9), -int(x.get("id") or 0)))
    out_items = out_items[: int(limit)]
    _apply_contacted_flags(db, me, out_items)
    return {"items": out_items}


@app.get("/properties/{property_id:int}/contact")
def get_property_contact(
    property_id: int,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    limiter.hit(key=f"contact:{me.id}", limit=60, window_seconds=60, detail="Too many contact unlock requests")
    p = db.get(Property, int(property_id))
    if not p or p.status != "approved":
        raise HTTPException(status_code=404, detail="Property not found")
    owner = db.get(User, int(p.owner_id))
    if not owner or owner.approval_status != "approved":
        raise HTTPException(status_code=404, detail="Property not found")

    # If this property was already unlocked via free quota, return immediately.
    already_free = db.execute(
        select(FreeContactUsage.id).where((FreeContactUsage.user_id == me.id) & (FreeContactUsage.property_id == int(property_id)))
    ).first()
    if already_free:
        return {
            "adv_number": (p.ad_number or "").strip() or str(p.id),
            "owner_name": (owner.name or "").strip() or "Owner",
            "owner_company_name": (owner.company_name or "").strip(),
            "phone": p.contact_phone,
            "email": p.contact_email,
        }

    sub = db.execute(select(Subscription).where(Subscription.user_id == me.id)).scalar_one_or_none()
    subscribed = bool(sub and (sub.status or "").lower() == "active")

    # Abuse prevention: enforce plan contact_limit per active subscription period.
    _ensure_plans(db)
    now = dt.datetime.now(dt.timezone.utc)
    if subscribed:
        usub = (
            db.execute(
                select(UserSubscription)
                .where((UserSubscription.user_id == me.id) & (UserSubscription.active == True))  # noqa: E712
                .order_by(UserSubscription.id.desc())
            )
            .scalars()
            .first()
        )
        if usub:
            if usub.end_time and usub.end_time <= now:
                usub.active = False
                db.add(usub)
                # fall back to free quota below
                subscribed = False
            else:
                plan = db.get(SubscriptionPlan, usub.plan_id)
                limit = int(plan.contact_limit or 0) if plan else 0
                if limit > 0:
                    # Don't double-count repeated unlocks of the same property for the same subscription.
                    existing = db.execute(
                        select(ContactUsage.id).where(
                            (ContactUsage.user_id == me.id)
                            & (ContactUsage.property_id == int(property_id))
                            & (ContactUsage.subscription_id == usub.id)
                        )
                    ).first()
                    if not existing:
                        used_count = db.execute(
                            select(ContactUsage.id).where((ContactUsage.user_id == me.id) & (ContactUsage.subscription_id == usub.id))
                        ).all()
                        if len(used_count) >= limit:
                            raise HTTPException(status_code=429, detail="Contact unlock limit reached for your plan")
                        db.add(ContactUsage(user_id=me.id, property_id=int(property_id), subscription_id=usub.id))
        else:
            # Backward-compatibility: if legacy subscription is active but no user_subscriptions row exists,
            # still allow contact unlock (best-effort).
            pass

    if not subscribed:
        free_limit = _free_contact_limit()
        if free_limit <= 0:
            raise HTTPException(status_code=402, detail="Subscription required to unlock contact")

        free_count = db.execute(select(func.count(FreeContactUsage.id)).where(FreeContactUsage.user_id == me.id)).scalar() or 0
        if int(free_count) >= int(free_limit):
            raise HTTPException(status_code=402, detail="Subscription required to unlock contact")

        # Don't double-count repeated unlocks of the same property.
        existing_free2 = db.execute(
            select(FreeContactUsage.id).where((FreeContactUsage.user_id == me.id) & (FreeContactUsage.property_id == int(property_id)))
        ).first()
        if not existing_free2:
            db.add(FreeContactUsage(user_id=me.id, property_id=int(property_id)))

    # Notify the customer via email + SMS (best-effort).
    adv_no = (p.ad_number or "").strip() or str(p.id)
    owner_name = (owner.name or "").strip() or "Owner"
    owner_phone = (p.contact_phone or "").strip()
    owner_email_contact = (p.contact_email or "").strip()
    customer_email = (me.email or "").strip()
    customer_phone = (me.phone_normalized or me.phone or "").strip()
    try:
        if customer_email and "@" in customer_email:
            send_email(
                to_email=customer_email,
                subject=f"Contact details for Ad #{adv_no}",
                text=(
                    f"Ad number: {adv_no}\n"
                    f"Owner name: {owner_name}\n"
                    f"Owner phone: {owner_phone or 'N/A'}\n"
                    f"Owner email: {owner_email_contact or 'N/A'}\n"
                    f"Owner company: {(owner.company_name or '').strip() or 'N/A'}\n"
                ),
            )
    except Exception:
        # Never block contact unlock due to notification errors.
        pass
    try:
        if customer_phone:
            send_sms(
                to_phone=customer_phone,
                text=f"Ad #{adv_no} contact: {owner_name} {owner_phone or ''} {owner_email_contact or ''}".strip(),
            )
    except Exception:
        pass

    return {
        "adv_number": adv_no,
        "owner_name": owner_name,
        "owner_company_name": (owner.company_name or "").strip(),
        "phone": p.contact_phone,
        "email": p.contact_email,
    }


@app.get("/owner/properties")
def owner_list_properties(
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if me.role not in {"user", "owner", "admin"}:
        raise HTTPException(status_code=403, detail="Login required")
    stmt = select(Property).options(selectinload(Property.images)).where(Property.owner_id == me.id).order_by(Property.created_at.desc(), Property.id.desc())
    items = [_property_out(p, owner=me, include_unapproved_images=True, include_internal=True) for p in db.execute(stmt).scalars().all()]
    return {"items": items}


@app.delete("/owner/properties/{property_id:int}")
def owner_delete_property(
    property_id: int,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if me.role not in {"user", "owner", "admin"}:
        raise HTTPException(status_code=403, detail="Login required")
    p = db.get(Property, int(property_id))
    if not p:
        raise HTTPException(status_code=404, detail="Ad not found")
    if me.role != "admin" and int(p.owner_id) != int(me.id):
        raise HTTPException(status_code=403, detail="Only the owner who created the ad can delete it")

    # Best-effort: delete uploaded media (Cloudinary and/or local disk).
    try:
        for img in (p.images or []):
            if (img.cloudinary_public_id or "").strip():
                rt = "video" if str(img.content_type or "").lower().startswith("video/") else "image"
                cloudinary_destroy(public_id=img.cloudinary_public_id, resource_type=rt)
            fp = (img.file_path or "").strip().lstrip("/")
            if fp and not fp.startswith("http"):
                disk_path = os.path.join(_uploads_dir(), fp)
                try:
                    if os.path.exists(disk_path):
                        os.remove(disk_path)
                except Exception:
                    pass
    except Exception:
        pass

    # Remove dependent rows first (avoid FK issues).
    db.execute(delete(FreeContactUsage).where(FreeContactUsage.property_id == int(property_id)))
    db.execute(delete(ContactUsage).where(ContactUsage.property_id == int(property_id)))
    db.execute(delete(SavedProperty).where(SavedProperty.property_id == int(property_id)))
    db.execute(delete(PropertyImage).where(PropertyImage.property_id == int(property_id)))
    db.execute(delete(Property).where(Property.id == int(property_id)))
    _log_moderation(db, actor_user_id=me.id, entity_type="property", entity_id=int(property_id), action="delete", reason="")
    return {"ok": True}


# -----------------------
# Owner flow: create listing (images uploaded separately)
# -----------------------
@app.post("/owner/properties")
def owner_create_property(
    data: PropertyCreateIn,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if me.role not in {"user", "owner", "admin"}:
        raise HTTPException(status_code=403, detail="Login required")
    if _is_guest_account(me):
        raise HTTPException(status_code=403, detail="Please register/login to publish ads")
    if me.role == "owner" and (me.approval_status or "") != "approved":
        raise HTTPException(status_code=403, detail="Owner account is pending admin approval")

    district = (data.district or "").strip()
    state = (data.state or "").strip()
    area = (data.area or "").strip()
    _validate_location_selection(state=state, district=district, area=area)

    lat = data.gps_lat
    lng = data.gps_lng
    lat_f: float | None = None
    lng_f: float | None = None
    # GPS is optional if State/District/Area are selected.
    # If provided, both coordinates must be valid.
    if lat is not None or lng is not None:
        if lat is None or lng is None:
            raise HTTPException(status_code=400, detail="Provide both GPS latitude and longitude (or omit both)")
        try:
            lat_f = float(lat)
            lng_f = float(lng)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid GPS coordinates")
        if not (-90.0 <= lat_f <= 90.0) or not (-180.0 <= lng_f <= 180.0):
            raise HTTPException(status_code=400, detail="Invalid GPS coordinates")
    address = (data.address or "").strip() or (data.location or "").strip()
    address_norm = _norm_key(address)
    # Enforce: posting contact phone must match the user's registered phone.
    # (UI also locks this field, but backend must enforce.)
    if me.role != "admin":
        contact_phone = str(getattr(me, "phone", "") or "").strip()
    else:
        contact_phone = (data.contact_phone or "").strip()
    contact_phone_norm = _norm_phone(contact_phone)
    if me.role != "admin" and not contact_phone_norm:
        raise HTTPException(status_code=400, detail="Your profile phone number is required to publish ads")
    company_name = (data.company_name or "").strip()
    company_name_norm = _norm_key(company_name)

    # Optionally update the owner's company name profile when provided.
    if company_name:
        me.company_name = company_name
        me.company_name_normalized = company_name_norm
        db.add(me)

    # Duplicate prevention:
    # - Address duplicates are allowed (user requested).
    # - Phone number is enforced to be the user's registered phone; do not block multiple ads by same phone.

    p = Property(
        owner_id=me.id,
        ad_number=_ensure_property_ad_number(db),
        title=(data.title or "").strip() or "Untitled",
        description=(data.description or "").strip(),
        property_type=(data.property_type or "apartment").strip(),
        rent_sale=(data.rent_sale or "rent").strip(),
        price=int(data.price or 0),
        location=(data.location or "").strip(),
        address=address,
        address_normalized=address_norm,
        state=state,
        district=district,
        area=area,
        state_normalized=_norm_key(state),
        district_normalized=_norm_key(district),
        area_normalized=_norm_key(area),
        gps_lat=lat_f,
        gps_lng=lng_f,
        amenities_json=json.dumps(list(data.amenities or [])),
        availability=(data.availability or "available").strip(),
        # Make newly posted ads visible immediately.
        # Admins can still suspend/reject later via moderation endpoints.
        status="approved",
        contact_phone=contact_phone,
        contact_phone_normalized=contact_phone_norm,
        contact_email=(data.contact_email or "").strip(),
        # IMPORTANT: allow duplicate addresses by default (DB has a unique index
        # that applies only when allow_duplicate_address=false).
        allow_duplicate_address=True,
        updated_at=dt.datetime.now(dt.timezone.utc),
    )
    db.add(p)
    db.flush()
    _log_moderation(db, actor_user_id=me.id, entity_type="property", entity_id=p.id, action="create", reason="")
    return {"id": p.id, "ad_number": (p.ad_number or "").strip() or str(p.id), "status": p.status}


@app.patch("/owner/properties/{property_id:int}")
def owner_update_property(
    property_id: int,
    data: PropertyUpdateIn,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Owner can edit their own ad. Admin can edit any ad.
    """
    if me.role not in {"user", "owner", "admin"}:
        raise HTTPException(status_code=403, detail="Login required")
    if _is_guest_account(me):
        raise HTTPException(status_code=403, detail="Please register/login to edit ads")

    p = db.get(Property, int(property_id))
    if not p:
        raise HTTPException(status_code=404, detail="Ad not found")
    if me.role != "admin" and int(p.owner_id) != int(me.id):
        raise HTTPException(status_code=403, detail="Only the owner who created the ad can edit it")

    # Apply updates (only fields provided by client).
    if data.title is not None:
        title = (data.title or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="Title is required")
        p.title = title
    if data.description is not None:
        p.description = (data.description or "").strip()
    if data.property_type is not None:
        p.property_type = (data.property_type or "").strip() or p.property_type
    if data.rent_sale is not None:
        rs = (data.rent_sale or "").strip().lower()
        if rs and rs not in {"rent", "sale"}:
            raise HTTPException(status_code=400, detail="Invalid rent_sale")
        p.rent_sale = rs or p.rent_sale
    if data.price is not None:
        try:
            p.price = int(data.price or 0)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid price")
    if data.location is not None:
        p.location = (data.location or "").strip()
    if data.address is not None:
        address = (data.address or "").strip()
        p.address = address
        p.address_normalized = _norm_key(address)
    if data.amenities is not None:
        try:
            p.amenities_json = json.dumps(list(data.amenities or []))
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid amenities")
    if data.availability is not None:
        p.availability = (data.availability or "").strip() or p.availability
    if data.contact_phone is not None:
        # Enforce: users cannot change contact phone on ads; it must match their profile.
        if me.role != "admin":
            ph = str(getattr(me, "phone", "") or "").strip()
        else:
            ph = (data.contact_phone or "").strip()
        p.contact_phone = ph
        p.contact_phone_normalized = _norm_phone(ph)
    if data.contact_email is not None:
        p.contact_email = (data.contact_email or "").strip()

    # Optional company name update: also updates owner profile if owner edits.
    if data.company_name is not None:
        company_name = (data.company_name or "").strip()
        if company_name and me.role != "admin":
            me.company_name = company_name
            me.company_name_normalized = _norm_key(company_name)
            db.add(me)

    # GPS updates (if explicitly provided).
    if data.gps_lat is not None or data.gps_lng is not None:
        if data.gps_lat is None or data.gps_lng is None:
            raise HTTPException(status_code=400, detail="Provide both GPS latitude and longitude (or omit both)")
        try:
            lat_f = float(data.gps_lat)
            lng_f = float(data.gps_lng)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid GPS coordinates")
        if not (-90.0 <= lat_f <= 90.0) or not (-180.0 <= lng_f <= 180.0):
            raise HTTPException(status_code=400, detail="Invalid GPS coordinates")
        p.gps_lat = lat_f
        p.gps_lng = lng_f

    # Location updates: if any part is provided, require the full trio after applying.
    loc_touched = (data.state is not None) or (data.district is not None) or (data.area is not None)
    if loc_touched:
        if data.state is not None:
            p.state = (data.state or "").strip()
            p.state_normalized = _norm_key(p.state)
        if data.district is not None:
            p.district = (data.district or "").strip()
            p.district_normalized = _norm_key(p.district)
        if data.area is not None:
            p.area = (data.area or "").strip()
            p.area_normalized = _norm_key(p.area)
        _validate_location_selection(state=p.state, district=p.district, area=p.area)

    p.updated_at = dt.datetime.now(dt.timezone.utc)
    db.add(p)
    _log_moderation(db, actor_user_id=me.id, entity_type="property", entity_id=p.id, action="update", reason="")

    owner = me if int(p.owner_id) == int(me.id) else db.get(User, int(p.owner_id))
    return {"ok": True, "property": _property_out(p, owner=owner or me, include_unapproved_images=True, include_internal=True)}


# -----------------------
# Admin moderation flow
# -----------------------
@app.get("/admin/properties/pending")
def admin_pending_properties(
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if me.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    items = [
        _property_out(p, include_unapproved_images=True, include_internal=True)
        for p in db.execute(select(Property).options(selectinload(Property.images)).where(Property.status == "pending").order_by(Property.id.desc()))
        .scalars()
        .all()
    ]
    return {"items": items}


@app.get("/admin/properties")
def admin_list_properties(
    db: Annotated[Session, Depends(get_db)],
    me: Annotated[User, Depends(get_current_user)],
    q: str | None = Query(default=None),
    rent_sale: str | None = Query(default=None),
    property_type: str | None = Query(default=None),
    max_price: int | None = Query(default=None),
    state: str | None = Query(default=None),
    district: str | None = Query(default=None),
    area: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    sort_budget: str | None = Query(default=None),  # top|bottom|asc|desc
    posted_within_days: int | None = Query(default=None, ge=1, le=365),
):
    """
    Admin-only listing endpoint with the same filters as the public `/properties`,
    but without the "approved only" restriction.
    """
    if me.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    state_in = (state or "").strip()
    district_in = (district or "").strip()
    area_in = (area or "").strip()
    state_norm = _norm_key(state_in)
    district_norm = _norm_key(district_in)
    area_list = _split_csv_values(area_in)
    area_norms = [_norm_key(x) for x in area_list]
    area_norms = [x for x in area_norms if x]
    area_norm = _norm_key(area_in)

    stmt = (
        select(Property, User)
        .options(selectinload(Property.images))
        .join(User, Property.owner_id == User.id)
    )

    st = (status or "").strip().lower()
    if st and st != "any":
        stmt = stmt.where(Property.status == st)

    sb = (sort_budget or "").strip().lower()
    if sb in {"top", "desc", "high"}:
        stmt = stmt.order_by(Property.price.desc(), Property.id.desc())
    elif sb in {"bottom", "asc", "low"}:
        stmt = stmt.order_by(Property.price.asc(), Property.id.desc())
    else:
        stmt = stmt.order_by(Property.id.desc())

    if state_norm:
        stmt = stmt.where(Property.state_normalized == state_norm)
    if district_norm:
        stmt = stmt.where(Property.district_normalized == district_norm)
    if area_norms:
        stmt = stmt.where(Property.area_normalized.in_(area_norms))
    elif area_norm:
        stmt = stmt.where(Property.area_normalized == area_norm)
    if q:
        q_like = f"%{q.strip()}%"
        stmt = stmt.where((Property.title.ilike(q_like)) | (Property.location.ilike(q_like)))
    if rent_sale:
        stmt = stmt.where(Property.rent_sale == rent_sale)
    if property_type:
        stmt = stmt.where(Property.property_type == property_type)
    if max_price is not None:
        stmt = stmt.where(Property.price <= int(max_price))
    if posted_within_days:
        now = dt.datetime.now(dt.timezone.utc)
        stmt = stmt.where(Property.created_at >= (now - dt.timedelta(days=int(posted_within_days))))

    rows = db.execute(stmt.limit(int(limit))).all()
    items: list[dict[str, Any]] = []
    for (p, u) in rows:
        items.append(_property_out(p, owner=u, include_unapproved_images=True, include_internal=True))
    return {"items": items}


@app.patch("/admin/properties/{property_id:int}")
def admin_update_property(
    property_id: int,
    data: PropertyUpdateIn,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if me.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    # Reuse owner/admin update logic (admin can edit any ad).
    return owner_update_property(property_id=property_id, data=data, me=me, db=db)


@app.delete("/admin/properties/{property_id:int}")
def admin_delete_property(
    property_id: int,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if me.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    p = db.get(Property, int(property_id))
    if not p:
        raise HTTPException(status_code=404, detail="Property not found")

    # Best-effort: delete uploaded media (Cloudinary and/or local disk).
    try:
        for img in (p.images or []):
            if (img.cloudinary_public_id or "").strip():
                rt = "video" if str(img.content_type or "").lower().startswith("video/") else "image"
                cloudinary_destroy(public_id=img.cloudinary_public_id, resource_type=rt)
            fp = (img.file_path or "").strip().lstrip("/")
            if fp and not fp.startswith("http"):
                disk_path = os.path.join(_uploads_dir(), fp)
                try:
                    if os.path.exists(disk_path):
                        os.remove(disk_path)
                except Exception:
                    pass
    except Exception:
        pass

    # Remove dependent rows first (avoid FK issues).
    db.execute(delete(FreeContactUsage).where(FreeContactUsage.property_id == int(property_id)))
    db.execute(delete(ContactUsage).where(ContactUsage.property_id == int(property_id)))
    db.execute(delete(PropertyImage).where(PropertyImage.property_id == int(property_id)))
    db.execute(delete(SavedProperty).where(SavedProperty.property_id == int(property_id)))
    db.execute(delete(Property).where(Property.id == int(property_id)))
    _log_moderation(db, actor_user_id=me.id, entity_type="property", entity_id=int(property_id), action="delete", reason="")
    return {"ok": True}


@app.post("/admin/properties/{property_id:int}/approve")
def admin_approve_property(
    property_id: int,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    data: ModerateIn | None = None,
):
    if me.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    p = db.get(Property, int(property_id))
    if not p:
        raise HTTPException(status_code=404, detail="Property not found")
    p.status = "approved"
    p.moderation_reason = ""
    p.updated_at = dt.datetime.now(dt.timezone.utc)
    db.add(p)
    _log_moderation(db, actor_user_id=me.id, entity_type="property", entity_id=p.id, action="approve", reason="")
    return {"ok": True}


@app.post("/admin/properties/{property_id:int}/reject")
def admin_reject_property(
    property_id: int,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    data: ModerateIn | None = None,
):
    if me.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    p = db.get(Property, int(property_id))
    if not p:
        raise HTTPException(status_code=404, detail="Property not found")
    p.status = "rejected"
    p.moderation_reason = (data.reason if data else "") or ""
    p.updated_at = dt.datetime.now(dt.timezone.utc)
    db.add(p)
    _log_moderation(db, actor_user_id=me.id, entity_type="property", entity_id=p.id, action="reject", reason=p.moderation_reason)
    return {"ok": True}


@app.post("/admin/properties/{property_id:int}/suspend")
def admin_suspend_property(
    property_id: int,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    data: ModerateIn | None = None,
):
    if me.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    p = db.get(Property, int(property_id))
    if not p:
        raise HTTPException(status_code=404, detail="Property not found")
    p.status = "suspended"
    p.moderation_reason = (data.reason if data else "") or ""
    p.updated_at = dt.datetime.now(dt.timezone.utc)
    db.add(p)
    _log_moderation(db, actor_user_id=me.id, entity_type="property", entity_id=p.id, action="suspend", reason=p.moderation_reason)
    return {"ok": True}


@app.post("/admin/properties/{property_id:int}/allow-duplicates")
def admin_allow_duplicates(
    property_id: int,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    data: AllowDuplicatesIn,
):
    if me.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    p = db.get(Property, int(property_id))
    if not p:
        raise HTTPException(status_code=404, detail="Property not found")
    changed = False
    if data.allow_duplicate_address is not None:
        p.allow_duplicate_address = bool(data.allow_duplicate_address)
        changed = True
    if data.allow_duplicate_phone is not None:
        p.allow_duplicate_phone = bool(data.allow_duplicate_phone)
        changed = True
    if changed:
        p.updated_at = dt.datetime.now(dt.timezone.utc)
        db.add(p)
        _log_moderation(
            db,
            actor_user_id=me.id,
            entity_type="property",
            entity_id=p.id,
            action="allow_duplicates",
            reason=(data.reason or "").strip(),
        )
    return {
        "ok": True,
        "allow_duplicate_address": p.allow_duplicate_address,
        "allow_duplicate_phone": p.allow_duplicate_phone,
    }


@app.get("/admin/owners/pending")
def admin_pending_owners(
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if me.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    owners = (
        db.execute(
            select(User)
            .where((User.role == "owner") & (User.approval_status == "pending"))
            .order_by(User.id.desc())
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": o.id,
                "email": o.email,
                "username": o.username,
                "phone": o.phone,
                "name": o.name,
                "state": o.state,
                "district": o.district,
                "owner_category": o.owner_category,
                "company_name": o.company_name,
                "company_description": o.company_description,
                "company_address": o.company_address,
                "approval_status": o.approval_status,
                "approval_reason": o.approval_reason,
            }
            for o in owners
        ]
    }


@app.post("/admin/owners/{owner_id}/approve")
def admin_approve_owner(
    owner_id: int,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    data: ModerateIn | None = None,
):
    if me.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    u = db.get(User, int(owner_id))
    if not u or u.role != "owner":
        raise HTTPException(status_code=404, detail="Owner not found")
    u.approval_status = "approved"
    u.approval_reason = ""
    db.add(u)
    _log_moderation(db, actor_user_id=me.id, entity_type="user", entity_id=u.id, action="approve", reason="")
    return {"ok": True}


@app.post("/admin/owners/{owner_id}/reject")
def admin_reject_owner(
    owner_id: int,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    data: ModerateIn | None = None,
):
    if me.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    u = db.get(User, int(owner_id))
    if not u or u.role != "owner":
        raise HTTPException(status_code=404, detail="Owner not found")
    u.approval_status = "rejected"
    u.approval_reason = (data.reason if data else "") or ""
    db.add(u)
    _log_moderation(db, actor_user_id=me.id, entity_type="user", entity_id=u.id, action="reject", reason=u.approval_reason)
    return {"ok": True}


@app.post("/admin/owners/{owner_id}/suspend")
def admin_suspend_owner(
    owner_id: int,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    data: ModerateIn | None = None,
):
    if me.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    u = db.get(User, int(owner_id))
    if not u or u.role != "owner":
        raise HTTPException(status_code=404, detail="Owner not found")
    u.approval_status = "suspended"
    u.approval_reason = (data.reason if data else "") or ""
    db.add(u)
    _log_moderation(db, actor_user_id=me.id, entity_type="user", entity_id=u.id, action="suspend", reason=u.approval_reason)
    return {"ok": True}


# -----------------------
# Admin: user administration
# -----------------------
@app.get("/admin/users")
def admin_list_users(
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    q: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    if me.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    qq = (q or "").strip().lower()

    stmt = select(User).order_by(User.created_at.desc(), User.id.desc())
    if qq:
        # best-effort search across name/email/phone/username
        stmt = stmt.where(
            (func.lower(User.email).contains(qq))
            | (func.lower(User.username).contains(qq))
            | (func.lower(User.name).contains(qq))
            | (func.lower(User.phone).contains(qq))
        )
    users = db.execute(stmt.limit(int(limit))).scalars().all()
    ids = [int(u.id) for u in users]

    counts: dict[int, int] = {}
    if ids:
        rows = db.execute(select(Property.owner_id, func.count(Property.id)).where(Property.owner_id.in_(ids)).group_by(Property.owner_id)).all()
        for owner_id, cnt in rows:
            try:
                counts[int(owner_id)] = int(cnt or 0)
            except Exception:
                continue

    items: list[dict[str, Any]] = []
    for u in users:
        items.append(
            {
                "id": u.id,
                "email": u.email,
                "username": u.username,
                "name": u.name,
                "phone": u.phone,
                "role": u.role,
                "approval_status": u.approval_status,
                "approval_reason": u.approval_reason,
                "created_at": u.created_at.isoformat() if getattr(u, "created_at", None) else "",
                "total_posts": int(counts.get(int(u.id), 0)),
            }
        )
    return {"items": items}


@app.get("/admin/users/{user_id:int}")
def admin_get_user(
    user_id: int,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if me.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    u = db.get(User, int(user_id))
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    stmt = (
        select(Property)
        .options(selectinload(Property.images))
        .where(Property.owner_id == int(u.id))
        .order_by(Property.created_at.desc(), Property.id.desc())
    )
    props = db.execute(stmt).scalars().all()
    items = [_property_out(p, owner=u, include_unapproved_images=True, include_internal=True) for p in props]

    return {
        "user": {
            "id": u.id,
            "email": u.email,
            "username": u.username,
            "name": u.name,
            "phone": u.phone,
            "role": u.role,
            "approval_status": u.approval_status,
            "approval_reason": u.approval_reason,
            "created_at": u.created_at.isoformat() if getattr(u, "created_at", None) else "",
        },
        "total_posts": len(items),
        "posts": items,
    }


@app.post("/admin/users/{user_id}/suspend")
def admin_suspend_user(
    user_id: int,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    data: ModerateIn | None = None,
):
    if me.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    if int(user_id) == int(me.id):
        raise HTTPException(status_code=400, detail="Cannot suspend your own admin account")
    u = db.get(User, int(user_id))
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if (u.role or "").lower() == "admin":
        raise HTTPException(status_code=400, detail="Cannot suspend admin accounts")
    u.approval_status = "suspended"
    u.approval_reason = (data.reason if data else "") or ""
    db.add(u)
    _log_moderation(db, actor_user_id=me.id, entity_type="user", entity_id=u.id, action="suspend", reason=u.approval_reason)
    return {"ok": True}


@app.post("/admin/users/{user_id}/approve")
def admin_approve_user(
    user_id: int,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if me.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    u = db.get(User, int(user_id))
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if (u.role or "").lower() == "admin":
        raise HTTPException(status_code=400, detail="Cannot modify admin accounts")
    u.approval_status = "approved"
    u.approval_reason = ""
    db.add(u)
    _log_moderation(db, actor_user_id=me.id, entity_type="user", entity_id=u.id, action="approve", reason="")
    return {"ok": True}


@app.post("/admin/properties/{property_id:int}/spam")
def admin_mark_property_spam(
    property_id: int,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    data: ModerateIn | None = None,
):
    if me.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    p = db.get(Property, int(property_id))
    if not p:
        raise HTTPException(status_code=404, detail="Ad not found")
    p.status = "suspended"
    p.moderation_reason = "SPAM"
    db.add(p)
    _log_moderation(db, actor_user_id=me.id, entity_type="property", entity_id=int(property_id), action="spam", reason=(data.reason if data else "") or "")
    return {"ok": True}


@app.get("/admin/images/pending")
def admin_pending_images(
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if me.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    imgs = (
        db.execute(select(PropertyImage).where(PropertyImage.status == "pending").order_by(PropertyImage.id.desc()))
        .scalars()
        .all()
    )
    out: list[dict[str, Any]] = []
    for img in imgs:
        p = db.get(Property, int(img.property_id))
        owner = db.get(User, int(p.owner_id)) if p else None
        out.append(
            {
                "id": img.id,
                "property_id": img.property_id,
                "property_title": p.title if p else "",
                "owner_id": owner.id if owner else None,
                "owner_company_name": owner.company_name if owner else "",
                "url": _public_image_url_if_exists(img.file_path),
                "image_hash": img.image_hash,
                "status": img.status,
                "original_filename": img.original_filename,
                "content_type": img.content_type,
                "size_bytes": img.size_bytes,
                "moderation_reason": img.moderation_reason,
            }
        )
    return {"items": out}


@app.post("/admin/images/{image_id}/approve")
def admin_approve_image(
    image_id: int,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    data: ModerateIn | None = None,
):
    if me.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    img = db.get(PropertyImage, int(image_id))
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    img.status = "approved"
    img.moderation_reason = ""
    db.add(img)
    _log_moderation(db, actor_user_id=me.id, entity_type="property_image", entity_id=img.id, action="approve", reason="")
    return {"ok": True}


@app.post("/admin/images/{image_id}/reject")
def admin_reject_image(
    image_id: int,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    data: ModerateIn | None = None,
):
    if me.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    img = db.get(PropertyImage, int(image_id))
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    img.status = "rejected"
    img.moderation_reason = (data.reason if data else "") or ""
    db.add(img)
    _log_moderation(db, actor_user_id=me.id, entity_type="property_image", entity_id=img.id, action="reject", reason=img.moderation_reason)
    return {"ok": True}


@app.post("/admin/images/{image_id}/suspend")
def admin_suspend_image(
    image_id: int,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    data: ModerateIn | None = None,
):
    if me.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    img = db.get(PropertyImage, int(image_id))
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    img.status = "suspended"
    img.moderation_reason = (data.reason if data else "") or ""
    db.add(img)
    _log_moderation(db, actor_user_id=me.id, entity_type="property_image", entity_id=img.id, action="suspend", reason=img.moderation_reason)
    return {"ok": True}


@app.get("/admin/logs")
def admin_logs(
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    entity_type: str | None = Query(default=None),
    entity_id: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
):
    if me.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    stmt = select(ModerationLog).order_by(ModerationLog.id.desc()).limit(int(limit))
    if entity_type:
        stmt = stmt.where(ModerationLog.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(ModerationLog.entity_id == int(entity_id))
    logs = db.execute(stmt).scalars().all()
    return {
        "items": [
            {
                "id": l.id,
                "actor_user_id": l.actor_user_id,
                "entity_type": l.entity_type,
                "entity_id": l.entity_id,
                "action": l.action,
                "reason": l.reason,
                "created_at": l.created_at,
            }
            for l in logs
        ]
    }


@app.post("/admin/auth/login")
def admin_login(data: AdminLoginIn, db: Annotated[Session, Depends(get_db)]):
    identifier = (data.identifier or "").strip()
    phone_norm = _norm_phone(identifier)
    user = db.execute(
        select(User).where(
            (User.email == identifier.lower())
            | (User.username == identifier)
            | (User.phone == identifier)
            | ((User.phone_normalized == phone_norm) & (User.phone_normalized != ""))
        )
    ).scalar_one_or_none()
    if not user or user.role != "admin" or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    token = create_access_token(user_id=user.id, role=user.role)
    return {"access_token": token, "user": {"id": user.id, "email": user.email, "name": user.name, "role": user.role}}


@app.get("/admin/revenue")
def admin_revenue(
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Revenue dashboard (basic):
    Aggregates validated subscriptions by plan.
    """
    if (me.role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    _ensure_plans(db)
    items = []
    for p in db.execute(select(SubscriptionPlan)).scalars().all():
        subs = db.execute(select(UserSubscription).where(UserSubscription.plan_id == p.id)).scalars().all()
        count = len(subs)
        items.append(
            {
                "plan_id": p.id,
                "name": p.name,
                "price_inr": int(p.price_inr or 0),
                "subscriptions": count,
                "revenue_inr": int(p.price_inr or 0) * count,
            }
        )
    items.sort(key=lambda x: x["revenue_inr"], reverse=True)
    return {"items": items}


@app.post("/properties/{property_id:int}/images")
def upload_property_image(
    property_id: int,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
    sort_order: int = Query(default=0),
):
    """
    Upload an image/video for a property listing.
    Note: This stores the file locally. For production, swap to S3/GCS/etc.
    """
    p = db.get(Property, int(property_id))
    if not p:
        raise HTTPException(status_code=404, detail="Property not found")
    if me.role != "admin" and p.owner_id != me.id:
        raise HTTPException(status_code=403, detail="Not allowed")
    if _is_guest_account(me):
        raise HTTPException(status_code=403, detail="Please register/login to publish ads")
    if me.role == "owner" and (me.approval_status or "") != "approved":
        raise HTTPException(status_code=403, detail="Owner account is pending admin approval")

    content_type = (file.content_type or "").lower().strip()
    guessed_type = (mimetypes.guess_type(file.filename or "")[0] or "").lower().strip()
    if not content_type or content_type == "application/octet-stream":
        content_type = guessed_type or content_type
    is_image = content_type.startswith("image/")
    is_video = content_type.startswith("video/")
    if not is_image and not is_video:
        ext = os.path.splitext(file.filename or "")[1].lower()
        image_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
        video_exts = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}
        if ext in image_exts:
            is_image = True
            content_type = guessed_type or "image/*"
        elif ext in video_exts:
            is_video = True
            content_type = guessed_type or "video/*"
    if not is_image and not is_video:
        raise HTTPException(status_code=400, detail="Only image/video uploads are allowed")

    # Enforce per-ad media limits.
    max_images = 10
    max_videos = 1
    existing_media = db.execute(select(PropertyImage.content_type).where(PropertyImage.property_id == p.id)).scalars().all()
    existing_images = sum(1 for ct in existing_media if str(ct or "").lower().startswith("image/"))
    existing_videos = sum(1 for ct in existing_media if str(ct or "").lower().startswith("video/"))
    if is_image and existing_images >= max_images:
        raise HTTPException(status_code=400, detail=f"Maximum {max_images} images are allowed per ad")
    if is_video and existing_videos >= max_videos:
        raise HTTPException(status_code=400, detail=f"Maximum {max_videos} video is allowed per ad")

    # Read bytes once to compute hash and store on disk.
    try:
        raw = file.file.read()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid upload")
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload")

    if is_image:
        _raise_if_too_large(size_bytes=len(raw), max_bytes=_max_upload_image_bytes())
        # AI moderation (reject before any storage).
        mod = _openai_moderate_image(raw=raw)
        if bool(mod.get("flagged")):
            _log_moderation(
                db,
                actor_user_id=me.id,
                entity_type="property_media_upload",
                entity_id=int(p.id),
                action="reject",
                reason=f"Unsafe image rejected by AI moderation ({mod.get('summary')})",
            )
            raise HTTPException(status_code=400, detail="Unsafe media detected. Upload rejected.")
        stored_bytes = raw
        stored_ext = _safe_upload_ext(filename=(file.filename or ""), content_type=content_type)
        stored_content_type = content_type
    else:
        _raise_if_too_large(size_bytes=len(raw), max_bytes=_max_upload_video_bytes())
        # AI moderation (reject before any storage).
        mod = _openai_moderate_video(raw=raw)
        if bool(mod.get("flagged")):
            _log_moderation(
                db,
                actor_user_id=me.id,
                entity_type="property_media_upload",
                entity_id=int(p.id),
                action="reject",
                reason=f"Unsafe video rejected by AI moderation ({mod.get('summary')})",
            )
            raise HTTPException(status_code=400, detail="Unsafe media detected. Upload rejected.")
        stored_bytes = raw
        stored_ext = _safe_upload_ext(filename=(file.filename or ""), content_type=content_type)
        stored_content_type = content_type

    img_hash = _image_sha256_hex(stored_bytes)
    existing = db.execute(select(PropertyImage).where(PropertyImage.image_hash == img_hash)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Duplicate media detected (hash already exists)")

    requested_sort = int(sort_order)
    # Clients commonly upload all media with sort_order=0.
    # Keep DB uniqueness intact by auto-assigning the next available sort_order if needed.
    try:
        existing_orders = db.execute(select(PropertyImage.sort_order).where(PropertyImage.property_id == p.id)).scalars().all()
        used = {int(x or 0) for x in existing_orders}
    except Exception:
        used = set()
    if requested_sort in used:
        requested_sort = (max(used) + 1) if used else 0

    token = secrets.token_hex(8)
    safe_name = f"p{p.id}_{token}{stored_ext}"

    cloud_pid = ""
    stored_path = safe_name
    if cloudinary_enabled():
        try:
            url, pid = cloudinary_upload_bytes(
                raw=stored_bytes,
                resource_type=("image" if is_image else "video"),
                public_id=f"property_{p.id}_{token}",
                filename=(file.filename or "").strip() or safe_name,
                content_type=stored_content_type,
            )
        except Exception as e:
            logger.exception(
                "Cloudinary upload failed (property media) property_id=%s filename=%r content_type=%r size_bytes=%s",
                p.id,
                file.filename,
                stored_content_type,
                len(stored_bytes),
            )
            msg = str(e) or "Cloudinary upload failed"
            raise HTTPException(status_code=500, detail=f"Failed to upload to Cloudinary: {msg[:200]}")
        stored_path = url
        cloud_pid = pid
    else:
        disk_path = os.path.join(_uploads_dir(), safe_name)
        try:
            with open(disk_path, "wb") as out:
                out.write(stored_bytes)
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to save upload")

    img = PropertyImage(
        property_id=p.id,
        file_path=stored_path,
        cloudinary_public_id=cloud_pid,
        sort_order=int(requested_sort),
        image_hash=img_hash,
        original_filename=(file.filename or "").strip(),
        content_type=stored_content_type,
        size_bytes=int(len(stored_bytes)),
        # Make uploads visible immediately (AI moderation already ran before storage).
        status="approved",
        uploaded_by_user_id=me.id,
    )
    db.add(img)
    try:
        db.flush()
    except IntegrityError:
        # Best-effort: resolve a rare concurrent sort_order collision.
        db.rollback()
        max_sort = db.execute(select(func.max(PropertyImage.sort_order)).where(PropertyImage.property_id == p.id)).scalar()
        next_sort = int(max_sort or -1) + 1
        img = PropertyImage(
            property_id=p.id,
            file_path=stored_path,
            cloudinary_public_id=cloud_pid,
            sort_order=int(next_sort),
            image_hash=img_hash,
            original_filename=(file.filename or "").strip(),
            content_type=stored_content_type,
            size_bytes=int(len(stored_bytes)),
            status="approved",
            uploaded_by_user_id=me.id,
        )
        db.add(img)
        db.flush()
    _log_moderation(db, actor_user_id=me.id, entity_type="property_image", entity_id=img.id, action="upload", reason="")
    return {
        "id": img.id,
        "url": _public_image_url(img.file_path),
        "sort_order": img.sort_order,
        "status": img.status,
        "image_hash": img.image_hash,
    }


# -----------------------
# Optional: serve the web UI (React build) from /
# -----------------------
def _web_dist_dir() -> str:
    # backend/app/main.py -> /workspace/backend/app
    # ../../web/dist -> /workspace/web/dist
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "web", "dist"))


def _web_assets_dir() -> str:
    return os.path.join(_web_dist_dir(), "assets")


def _web_index_html() -> str:
    return os.path.join(_web_dist_dir(), "index.html")


# If the React build exists, serve its hashed assets from /assets.
# Without this, the SPA fallback can accidentally return index.html for JS/CSS requests,
# causing a blank white page (scripts never execute due to wrong content-type).
_assets_dir = _web_assets_dir()
if os.path.isdir(_assets_dir):
    app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")


@app.get("/", include_in_schema=False)
def root():
    """
    If the React app is built (web/dist), serve it.
    Otherwise show a small help page instead of JSON 404.
    """
    index_path = _web_index_html()
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse(
        """
        <!doctype html>
        <html>
          <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1" />
            <title>Quickrent4u</title>
            <style>
              body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; padding: 24px; line-height: 1.4; }
              code { background: #f5f5f5; padding: 2px 6px; border-radius: 6px; }
              pre { background: #f5f5f5; padding: 12px; border-radius: 10px; overflow: auto; }
              a { color: #0b57d0; text-decoration: none; }
              a:hover { text-decoration: underline; }
            </style>
          </head>
          <body>
            <h2>Backend is running (API)</h2>
            <p>
              You opened the API server root (<code>/</code>). The web UI is a separate React app in <code>web/</code>.
            </p>
            <h3>Run the web UI (dev)</h3>
            <pre><code>cd web
npm install
npm run dev</code></pre>
            <p>
              Then open the URL for the dev server (default port <code>5173</code>).
            </p>
            <h3>API docs</h3>
            <p>See interactive docs at <a href="/docs"><code>/docs</code></a>.</p>
          </body>
        </html>
        """.strip()
    )


@app.exception_handler(StarletteHTTPException)
async def spa_fallback_404(request, exc: StarletteHTTPException):
    """
    SPA fallback:
    - If the React build exists and a GET path isn't an API/static path, serve index.html.
    - Otherwise keep FastAPI's normal JSON error response.
    """
    if exc.status_code == 404 and request.method == "GET":
        index_path = _web_index_html()
        if os.path.exists(index_path):
            path = request.url.path
            is_api_or_static = path.startswith(
                (
                    "/auth",
                    "/assets",
                    "/locations",
                    "/properties",
                    "/owner",
                    "/uploads",
                    "/health",
                    "/docs",
                    "/openapi",
                    "/redoc",
                )
            )
            if not is_api_or_static:
                return FileResponse(index_path)
    # Fall back to the default FastAPI JSON shape.
    return HTMLResponse(status_code=exc.status_code, content=str({"detail": exc.detail}))
