from __future__ import annotations

import datetime as dt
import json
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session_scope
from app.models import OtpCode, Property, Subscription, User
from app.security import create_access_token, decode_access_token, hash_password, verify_password


app = FastAPI(title="Property Discovery API")


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


# -----------------------
# Schemas
# -----------------------
class RegisterIn(BaseModel):
    email: str
    username: str
    password: str = Field(min_length=6)
    name: str = ""
    country: str = ""
    gender: str = ""


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


# -----------------------
# Health
# -----------------------
@app.get("/health")
def health():
    return {"ok": True}


# -----------------------
# Auth
# -----------------------
@app.post("/auth/register")
def register(data: RegisterIn, db: Annotated[Session, Depends(get_db)]):
    email = data.email.strip().lower()
    username = data.username.strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email")
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Invalid username")

    exists = db.execute(select(User).where((User.email == email) | (User.username == username))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="User already exists")

    user = User(
        email=email,
        username=username,
        name=(data.name or "").strip(),
        country=(data.country or "").strip(),
        gender=(data.gender or "").strip(),
        role="user",
        password_hash=hash_password(data.password),
    )
    db.add(user)
    db.flush()
    # Ensure a subscription row exists.
    db.add(Subscription(user_id=user.id, status="inactive", provider="google_play"))
    return {"ok": True, "user_id": user.id}


@app.post("/auth/login/request-otp")
def login_request_otp(data: LoginRequestOtpIn, db: Annotated[Session, Depends(get_db)]):
    identifier = data.identifier.strip()
    user = db.execute(select(User).where((User.email == identifier.lower()) | (User.username == identifier))).scalar_one_or_none()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Demo OTP (replace with SMS/email provider).
    code = "123456"
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10)
    db.add(OtpCode(identifier=identifier, purpose="login", code=code, expires_at=expires))
    return {"ok": True, "message": "OTP sent (demo OTP: 123456)"}


@app.post("/auth/login/verify-otp")
def login_verify_otp(data: LoginVerifyOtpIn, db: Annotated[Session, Depends(get_db)]):
    identifier = data.identifier.strip()
    user = db.execute(select(User).where((User.email == identifier.lower()) | (User.username == identifier))).scalar_one_or_none()
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

    token = create_access_token(user_id=user.id, role=user.role)
    return {"access_token": token, "user": {"id": user.id, "email": user.email, "name": user.name, "role": user.role}}


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
    return {"access_token": token, "user": {"id": user.id, "email": user.email, "name": user.name, "role": user.role}}


@app.post("/auth/forgot/request-otp")
def forgot_request_otp(data: ForgotRequestOtpIn, db: Annotated[Session, Depends(get_db)]):
    identifier = data.identifier.strip()
    user = db.execute(select(User).where((User.email == identifier.lower()) | (User.username == identifier))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    code = "123456"
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10)
    db.add(OtpCode(identifier=identifier, purpose="forgot", code=code, expires_at=expires))
    return {"ok": True, "message": "OTP sent (demo OTP: 123456)"}


@app.post("/auth/forgot/reset")
def forgot_reset(data: ForgotResetIn, db: Annotated[Session, Depends(get_db)]):
    identifier = data.identifier.strip()
    user = db.execute(select(User).where((User.email == identifier.lower()) | (User.username == identifier))).scalar_one_or_none()
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


# -----------------------
# Properties (browse is free; contact is subscription-gated)
# -----------------------
def _property_out(p: Property) -> dict[str, Any]:
    try:
        amenities = json.loads(p.amenities_json or "[]") if p.amenities_json else []
    except Exception:
        amenities = []
    return {
        "id": p.id,
        "title": p.title,
        "description": p.description,
        "property_type": p.property_type,
        "rent_sale": p.rent_sale,
        "price": p.price,
        "price_display": f"{p.price:,}",
        "location": p.location,
        "location_display": p.location,
        "amenities": amenities,
        "availability": p.availability,
        "status": p.status,
    }


@app.get("/properties")
def list_properties(
    db: Annotated[Session, Depends(get_db)],
    q: str | None = Query(default=None),
    rent_sale: str | None = Query(default=None),
    property_type: str | None = Query(default=None),
    max_price: int | None = Query(default=None),
):
    stmt = select(Property).where(Property.status == "approved").order_by(Property.id.desc())
    if q:
        q_like = f"%{q.strip()}%"
        stmt = stmt.where((Property.title.ilike(q_like)) | (Property.location.ilike(q_like)))
    if rent_sale:
        stmt = stmt.where(Property.rent_sale == rent_sale)
    if property_type:
        stmt = stmt.where(Property.property_type == property_type)
    if max_price is not None:
        stmt = stmt.where(Property.price <= int(max_price))

    items = [ _property_out(p) for p in db.execute(stmt).scalars().all() ]
    # Seed demo data if empty (first run).
    if not items:
        demo_owner = db.execute(select(User).where(User.username == "demo_owner")).scalar_one_or_none()
        if not demo_owner:
            demo_owner = User(
                email="owner@demo.local",
                username="demo_owner",
                name="Demo Owner",
                role="owner",
                password_hash=hash_password("password123"),
            )
            db.add(demo_owner)
            db.flush()
            db.add(Subscription(user_id=demo_owner.id, status="inactive", provider="google_play"))

        p1 = Property(
            owner_id=demo_owner.id,
            title="Modern Studio Near Metro",
            description="Bright studio with balcony.",
            property_type="studio",
            rent_sale="rent",
            price=1200,
            location="Downtown",
            amenities_json='["wifi","parking","gym"]',
            status="approved",
            contact_phone="+1 555 0100",
            contact_email="owner@demo.local",
        )
        p2 = Property(
            owner_id=demo_owner.id,
            title="Family House With Garden",
            description="3BR house, quiet neighborhood.",
            property_type="house",
            rent_sale="sale",
            price=250000,
            location="Greenwood",
            amenities_json='["garden","parking"]',
            status="approved",
            contact_phone="+1 555 0200",
            contact_email="owner@demo.local",
        )
        db.add_all([p1, p2])
        db.flush()
        items = [_property_out(p2), _property_out(p1)]

    return {"items": items}


@app.get("/properties/{property_id}")
def get_property(property_id: int, db: Annotated[Session, Depends(get_db)]):
    p = db.get(Property, int(property_id))
    if not p or p.status != "approved":
        raise HTTPException(status_code=404, detail="Property not found")
    return _property_out(p)


@app.get("/properties/{property_id}/contact")
def get_property_contact(
    property_id: int,
    me: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    p = db.get(Property, int(property_id))
    if not p or p.status != "approved":
        raise HTTPException(status_code=404, detail="Property not found")

    sub = db.execute(select(Subscription).where(Subscription.user_id == me.id)).scalar_one_or_none()
    if not sub or (sub.status or "").lower() != "active":
        raise HTTPException(status_code=402, detail="Subscription required to unlock contact")

    return {"phone": p.contact_phone, "email": p.contact_email}

