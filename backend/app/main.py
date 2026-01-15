from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import secrets
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import allowed_hosts, enforce_secure_secrets, otp_exp_minutes
from app.db import session_scope
from app.mailer import EmailSendError, send_email, send_otp_email
from app.rate_limit import limiter
from app.models import (
    ContactUsage,
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


app = FastAPI(title="ConstructHub API")

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

_CATEGORY_CATALOG_PATH = os.path.join(os.path.dirname(__file__), "category_catalog.json")


def _load_category_catalog() -> dict[str, Any]:
    try:
        with open(_CATEGORY_CATALOG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # Never break the API if the catalog file is missing/corrupt.
        return {"version": "0", "updated": "", "categories": []}


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


def _admin_otp_email() -> str:
    """
    Admin OTPs are routed to a fixed mailbox for operational control.
    Override with env `ADMIN_OTP_EMAIL` if needed.
    """
    return (os.environ.get("ADMIN_OTP_EMAIL") or "info@srtech.co.in").strip() or "info@srtech.co.in"


def _public_image_url(file_path: str) -> str:
    fp = (file_path or "").strip()
    if fp.startswith("http://") or fp.startswith("https://"):
        return fp
    fp = fp.lstrip("/")
    return f"/uploads/{fp}"


def _user_out(u: User) -> dict[str, Any]:
    img = (u.profile_image_path or "").strip()
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
        "profile_image_url": _public_image_url(img) if img else "",
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


def _new_ad_number() -> str:
    # 6-char uppercase alphanumeric.
    return "".join(secrets.choice(_AD_NUMBER_ALPHABET) for _ in range(6))


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
app.mount("/uploads", StaticFiles(directory=_uploads_dir()), name="uploads")


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
    address: str = ""
    amenities: list[str] = Field(default_factory=list)
    availability: str = "available"
    contact_phone: str = ""
    contact_email: str = ""
    # Optional: owner company name to display on ads.
    # This updates the owner's profile (User.company_name) when provided.
    company_name: str = ""


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
    catalog = _load_category_catalog()
    flat_items = _catalog_flat_items(catalog)
    return {
        "version": str(catalog.get("version") or ""),
        "updated": str(catalog.get("updated") or ""),
        "categories": catalog.get("categories") or [],
        # Owner categories are the same as selectable items.
        "owner_categories": [x.get("label") for x in flat_items if x.get("label")],
        "flat_items": flat_items,
    }


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
        return {"ok": True, "message": f"Admin OTP sent to {_admin_otp_email()}."}
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
    plans = [
        ("aggressive_10", "Aggressive", 10, 30, 10),
        ("instant_79", "Instant", 79, 30, 50),
        ("smart_monthly_199", "Smart", 199, 30, 200),
        ("business_quarterly_499", "Business", 499, 90, 1000),
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

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        ext = ".jpg" if content_type in {"image/jpeg", "image/jpg"} else ".png"

    try:
        raw = file.file.read()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid upload")
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload")

    safe_name = f"u{me.id}_{secrets.token_hex(8)}{ext}"
    disk_path = os.path.join(_uploads_dir(), safe_name)
    try:
        with open(disk_path, "wb") as out:
            out.write(raw)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to save upload")

    me.profile_image_path = safe_name
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
        for i in (p.images or []):
            if not include_unapproved_images and (i.status or "") != "approved":
                continue
            img_out: dict[str, Any] = {"id": i.id, "url": _public_image_url(i.file_path), "sort_order": i.sort_order}
            if include_internal:
                img_out["status"] = i.status
                img_out["image_hash"] = i.image_hash
            images.append(img_out)
    except Exception:
        images = []
    location_display = p.address or p.location
    o = owner or getattr(p, "owner", None)
    owner_name = (getattr(o, "name", "") or "").strip() if o else ""
    owner_company_name = (getattr(o, "company_name", "") or "").strip() if o else ""
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
        "amenities": amenities,
        "availability": p.availability,
        "status": p.status,
        "images": images,
        "created_at": p.created_at.isoformat() if getattr(p, "created_at", None) else "",
        "owner_name": owner_name,
        "owner_company_name": owner_company_name,
    }
    if include_internal:
        out["moderation_reason"] = p.moderation_reason
        out["address"] = p.address
        out["address_normalized"] = p.address_normalized
        out["contact_phone_normalized"] = p.contact_phone_normalized
        out["state_normalized"] = p.state_normalized
        out["district_normalized"] = p.district_normalized
        out["allow_duplicate_address"] = p.allow_duplicate_address
        out["allow_duplicate_phone"] = p.allow_duplicate_phone
    return out


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
    sort_budget: str | None = Query(default=None),  # top|bottom|asc|desc
    posted_within_days: int | None = Query(default=None, ge=1, le=365),
):
    state_in = (state or "").strip()
    district_in = (district or "").strip()
    if me:
        # If a logged-in user didn't pass filters, fall back to their profile.
        if not state_in and (me.state or "").strip():
            state_in = (me.state or "").strip()
        if not district_in and (me.district or "").strip():
            district_in = (me.district or "").strip()

    state_norm = _norm_key(state_in)
    district_norm = _norm_key(district_in)

    # Only approved listings from approved (non-suspended) owners are visible.
    stmt = (
        select(Property, User)
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
    if state_norm and district_norm:
        stmt = stmt.where((Property.state_normalized == state_norm) & (Property.district_normalized == district_norm))
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

    rows = db.execute(stmt).all()
    items = [_property_out(p, owner=u) for (p, u) in rows]
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
                    state_normalized=_norm_key("Karnataka"),
                    district_normalized=_norm_key("Bengaluru (Bangalore) Urban"),
                    address="Downtown",
                    address_normalized=_norm_key("Downtown"),
                    amenities_json='["wifi","parking","gym"]',
                    status="approved",
                    contact_phone="+1 555 0100",
                    contact_email="owner@demo.local",
                    contact_phone_normalized=_norm_phone("+1 555 0100"),
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
                    state_normalized=_norm_key("Karnataka"),
                    district_normalized=_norm_key("Bengaluru (Bangalore) Urban"),
                    address="Greenwood",
                    address_normalized=_norm_key("Greenwood"),
                    amenities_json='["garden","parking"]',
                    status="approved",
                    contact_phone="+1 555 0200",
                    contact_email="owner@demo.local",
                    contact_phone_normalized=_norm_phone("+1 555 0200"),
                )
                db.add_all([p1, p2])
                db.flush()
            except IntegrityError:
                # If two first-time requests race, one may violate unique indexes.
                # Roll back the failed insert attempt and proceed with the normal query.
                db.rollback()

            # Only return demo results if they match the requested filter.
            rows = db.execute(stmt).all()
            items = [_property_out(p, owner=u) for (p, u) in rows]

    return {"items": items}


@app.get("/properties/{property_id}")
def get_property(property_id: int, db: Annotated[Session, Depends(get_db)]):
    p = db.get(Property, int(property_id))
    if not p or p.status != "approved":
        raise HTTPException(status_code=404, detail="Property not found")
    owner = db.get(User, int(p.owner_id))
    if not owner or owner.approval_status != "approved":
        raise HTTPException(status_code=404, detail="Property not found")
    return _property_out(p, owner=owner)


@app.get("/properties/{property_id}/contact")
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

    sub = db.execute(select(Subscription).where(Subscription.user_id == me.id)).scalar_one_or_none()
    if not sub or (sub.status or "").lower() != "active":
        raise HTTPException(status_code=402, detail="Subscription required to unlock contact")

    # Abuse prevention: enforce plan contact_limit per active subscription period.
    _ensure_plans(db)
    now = dt.datetime.now(dt.timezone.utc)
    usub = (
        db.execute(
            select(UserSubscription)
            .where((UserSubscription.user_id == me.id) & (UserSubscription.active == True))  # noqa: E712
            .order_by(UserSubscription.id.desc())
        )
        .scalars()
        .first()
    )
    if not usub:
        raise HTTPException(status_code=402, detail="Subscription required to unlock contact")
    if usub.end_time and usub.end_time <= now:
        usub.active = False
        db.add(usub)
        raise HTTPException(status_code=402, detail="Subscription expired")

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

    # Notify the customer via email + SMS (best-effort).
    adv_no = (p.ad_number or "").strip() or str(p.id)
    owner_name = (owner.name or "").strip() or "Owner"
    owner_phone = (p.contact_phone or "").strip()
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
                text=f"Ad #{adv_no} contact: {owner_name} {owner_phone or ''}".strip(),
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
    stmt = select(Property).where(Property.owner_id == me.id).order_by(Property.created_at.desc(), Property.id.desc())
    items = [_property_out(p, owner=me, include_unapproved_images=True, include_internal=True) for p in db.execute(stmt).scalars().all()]
    return {"items": items}


@app.delete("/owner/properties/{property_id}")
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

    # Best-effort: delete uploaded image files from disk.
    try:
        for img in (p.images or []):
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

    db.delete(p)
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
    if me.role == "owner" and (me.approval_status or "") != "approved":
        raise HTTPException(status_code=403, detail="Owner account is pending admin approval")

    state = (data.state or "").strip() or (me.state or "").strip()
    district = (data.district or "").strip() or (me.district or "").strip()
    if not state or not district:
        raise HTTPException(status_code=400, detail="State and District are required")
    address = (data.address or "").strip() or (data.location or "").strip()
    address_norm = _norm_key(address)
    contact_phone = (data.contact_phone or "").strip()
    contact_phone_norm = _norm_phone(contact_phone)
    company_name = (data.company_name or "").strip()
    company_name_norm = _norm_key(company_name)

    # Optionally update the owner's company name profile when provided.
    if company_name:
        me.company_name = company_name
        me.company_name_normalized = company_name_norm
        db.add(me)

    # Duplicate prevention: address + phone (admin can create duplicates explicitly).
    if me.role != "admin":
        if address_norm:
            dup_addr = db.execute(
                select(Property.id).where(
                    (Property.address_normalized == address_norm) & (Property.allow_duplicate_address == False)  # noqa: E712
                )
            ).first()
            if dup_addr:
                raise HTTPException(status_code=409, detail="Duplicate address detected (admin override required)")
        if contact_phone_norm:
            dup_phone = db.execute(
                select(Property.id).where(
                    (Property.contact_phone_normalized == contact_phone_norm) & (Property.allow_duplicate_phone == False)  # noqa: E712
                )
            ).first()
            if dup_phone:
                raise HTTPException(status_code=409, detail="Duplicate listing phone detected (admin override required)")

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
        state_normalized=_norm_key(state),
        district_normalized=_norm_key(district),
        amenities_json=json.dumps(list(data.amenities or [])),
        availability=(data.availability or "available").strip(),
        # Make newly posted ads visible immediately.
        # Admins can still suspend/reject later via moderation endpoints.
        status="approved",
        contact_phone=contact_phone,
        contact_phone_normalized=contact_phone_norm,
        contact_email=(data.contact_email or "").strip(),
        updated_at=dt.datetime.now(dt.timezone.utc),
    )
    db.add(p)
    db.flush()
    _log_moderation(db, actor_user_id=me.id, entity_type="property", entity_id=p.id, action="create", reason="")
    return {"id": p.id, "ad_number": (p.ad_number or "").strip() or str(p.id), "status": p.status}


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
        for p in db.execute(select(Property).where(Property.status == "pending").order_by(Property.id.desc())).scalars().all()
    ]
    return {"items": items}


@app.post("/admin/properties/{property_id}/approve")
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


@app.post("/admin/properties/{property_id}/reject")
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


@app.post("/admin/properties/{property_id}/suspend")
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


@app.post("/admin/properties/{property_id}/allow-duplicates")
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
                "url": _public_image_url(img.file_path),
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


@app.post("/properties/{property_id}/images")
def upload_property_image(
    property_id: int,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
    sort_order: int = Query(default=0),
):
    """
    Upload an image for a property listing.
    Note: This stores the file locally. For production, swap to S3/GCS/etc.
    """
    p = db.get(Property, int(property_id))
    if not p:
        raise HTTPException(status_code=404, detail="Property not found")
    if me.role != "admin" and p.owner_id != me.id:
        raise HTTPException(status_code=403, detail="Not allowed")
    if me.role == "owner" and (me.approval_status or "") != "approved":
        raise HTTPException(status_code=403, detail="Owner account is pending admin approval")

    content_type = (file.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image uploads are allowed")

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        ext = ".jpg" if content_type in {"image/jpeg", "image/jpg"} else ".png"

    # Read bytes once to compute hash and store on disk.
    try:
        raw = file.file.read()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid upload")
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload")

    img_hash = _image_sha256_hex(raw)
    existing = db.execute(select(PropertyImage).where(PropertyImage.image_hash == img_hash)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Duplicate image detected (hash already exists)")

    safe_name = f"p{p.id}_{secrets.token_hex(8)}{ext}"
    disk_path = os.path.join(_uploads_dir(), safe_name)
    try:
        with open(disk_path, "wb") as out:
            out.write(raw)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to save upload")

    img = PropertyImage(
        property_id=p.id,
        file_path=safe_name,
        sort_order=int(sort_order),
        image_hash=img_hash,
        original_filename=(file.filename or "").strip(),
        content_type=(file.content_type or "").strip(),
        size_bytes=int(len(raw)),
        status="pending",
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
            <title>ConstructHub</title>
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
                    "/properties",
                    "/owner",
                    "/admin",
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
