from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, deferred, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    # Phone is indexed here; uniqueness is enforced via a partial unique index in migrations
    # so that empty strings don't collide.
    phone: Mapped[str] = mapped_column(String(32), default="", index=True)
    phone_normalized: Mapped[str] = mapped_column(String(32), default="", index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    state: Mapped[str] = mapped_column(String(80), default="")
    district: Mapped[str] = mapped_column(String(120), default="")
    # Last known GPS location (for distance calculations).
    gps_lat: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    gps_lng: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    # NOTE: Kept for backward compatibility with older mobile clients.
    gender: Mapped[str] = mapped_column(String(32), default="")
    role: Mapped[str] = mapped_column(String(32), default="user")  # user | owner | admin
    owner_category: Mapped[str] = mapped_column(String(120), default="")  # business type (for owners)
    # Owner/company profile fields
    company_name: Mapped[str] = mapped_column(String(255), default="", index=True)
    company_name_normalized: Mapped[str] = mapped_column(String(255), default="", index=True)
    company_description: Mapped[str] = mapped_column(Text, default="")
    company_address: Mapped[str] = mapped_column(String(512), default="", index=True)
    company_address_normalized: Mapped[str] = mapped_column(String(512), default="", index=True)

    # Profile image (optional). Stored as a relative uploads path or full URL.
    profile_image_path: Mapped[str] = mapped_column(String(512), default="")
    # Cloudinary public_id for profile image (optional).
    profile_image_cloudinary_public_id: Mapped[str] = mapped_column(String(255), default="")

    # Admin approval workflow for owners (role=owner)
    approval_status: Mapped[str] = mapped_column(String(40), default="approved")  # approved|pending|rejected|suspended
    approval_reason: Mapped[str] = mapped_column(Text, default="")

    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))

    properties = relationship("Property", back_populates="owner")
    subscription = relationship("Subscription", back_populates="user", uselist=False)


class OtpCode(Base):
    __tablename__ = "otp_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identifier: Mapped[str] = mapped_column(String(255), index=True)  # email/username/phone
    purpose: Mapped[str] = mapped_column(String(40), index=True)  # login | forgot
    code: Mapped[str] = mapped_column(String(12))
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(40), default="google_play")
    status: Mapped[str] = mapped_column(String(40), default="inactive")  # active | inactive
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    purchase_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))

    user = relationship("User", back_populates="subscription")


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    # Product ID from Google Play (e.g. smart_monthly_199)
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    price_inr: Mapped[int] = mapped_column(Integer, default=0)
    duration_days: Mapped[int] = mapped_column(Integer, default=30)
    contact_limit: Mapped[int] = mapped_column(Integer, default=0)


class UserSubscription(Base):
    __tablename__ = "user_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("subscription_plans.id"), index=True)
    purchase_token: Mapped[str] = mapped_column(String(255), unique=True)
    start_time: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))


class ContactUsage(Base):
    __tablename__ = "contact_usage"
    __table_args__ = (UniqueConstraint("user_id", "property_id", "subscription_id", name="uq_usage_user_property_sub"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"), index=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("user_subscriptions.id"), index=True)
    used_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))


class FreeContactUsage(Base):
    """
    Tracks free contact unlocks (first N unique properties per user).
    """

    __tablename__ = "free_contact_usage"
    __table_args__ = (UniqueConstraint("user_id", "property_id", name="uq_free_usage_user_property"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"), index=True)
    used_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # Public-facing ad/post number (6-char alphanumeric).
    ad_number: Mapped[str] = mapped_column(String(6), default="", index=True, unique=True)

    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    property_type: Mapped[str] = mapped_column(String(40), default="apartment")  # apartment/house/...
    # High-level group used by UI toggles (services vs property/material).
    # This is intentionally separate from `property_type` so custom categories still filter correctly.
    # NOTE: deferred so older DBs without the column won't crash on SELECT.
    # We conditionally write/filter on this column only when it exists.
    post_group: Mapped[str] = deferred(mapped_column(String(40), default="", index=True))
    rent_sale: Mapped[str] = mapped_column(String(10), default="rent")  # rent/sale
    price: Mapped[int] = mapped_column(Integer, default=0)

    # Display location (legacy) and normalized address fields for duplicate detection.
    location: Mapped[str] = mapped_column(String(255), default="")
    address: Mapped[str] = mapped_column(String(512), default="")
    address_normalized: Mapped[str] = mapped_column(String(512), default="", index=True)

    # Mandatory search filters (guest users must provide state+district)
    state: Mapped[str] = mapped_column(String(80), default="", index=True)
    district: Mapped[str] = mapped_column(String(120), default="", index=True)
    area: Mapped[str] = mapped_column(String(160), default="", index=True)
    state_normalized: Mapped[str] = mapped_column(String(80), default="", index=True)
    district_normalized: Mapped[str] = mapped_column(String(120), default="", index=True)
    area_normalized: Mapped[str] = mapped_column(String(160), default="", index=True)

    # GPS coordinates (captured at posting time).
    gps_lat: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    gps_lng: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)

    amenities_json: Mapped[str] = mapped_column(Text, default="[]")  # JSON-encoded list of strings

    availability: Mapped[str] = mapped_column(String(40), default="available")
    status: Mapped[str] = mapped_column(String(40), default="pending")  # pending/approved/rejected/suspended
    moderation_reason: Mapped[str] = mapped_column(Text, default="")

    contact_phone: Mapped[str] = mapped_column(String(40), default="")
    contact_phone_normalized: Mapped[str] = mapped_column(String(40), default="", index=True)
    contact_email: Mapped[str] = mapped_column(String(255), default="")

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))

    # Duplicate overrides (admin-controlled)
    allow_duplicate_address: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_duplicate_phone: Mapped[bool] = mapped_column(Boolean, default=False)

    owner = relationship("User", back_populates="properties")
    images = relationship("PropertyImage", back_populates="property", cascade="all, delete-orphan")


class SavedProperty(Base):
    __tablename__ = "saved_properties"
    __table_args__ = (UniqueConstraint("user_id", "property_id", name="uq_saved_user_property"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))


class PropertyImage(Base):
    __tablename__ = "property_images"
    __table_args__ = (UniqueConstraint("property_id", "sort_order", name="uq_property_image_sort"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"), index=True)
    file_path: Mapped[str] = mapped_column(String(512))  # relative path or URL
    # Cloudinary public_id for cleanup (optional).
    cloudinary_public_id: Mapped[str] = mapped_column(String(255), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # Metadata for duplicate detection and review.
    image_hash: Mapped[str] = mapped_column(String(64), default="", index=True)  # sha256 hex
    original_filename: Mapped[str] = mapped_column(String(255), default="")
    content_type: Mapped[str] = mapped_column(String(100), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="pending")  # pending/approved/rejected/suspended
    moderation_reason: Mapped[str] = mapped_column(Text, default="")
    uploaded_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))

    property = relationship("Property", back_populates="images")


class ModerationLog(Base):
    __tablename__ = "moderation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)  # user|property|property_image
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(40), index=True)  # approve|reject|suspend|create|upload
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))

