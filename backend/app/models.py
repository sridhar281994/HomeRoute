from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(20), default="", index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    state: Mapped[str] = mapped_column(String(80), default="")
    district: Mapped[str] = mapped_column(String(120), default="")
    # NOTE: Kept for backward compatibility with older mobile clients.
    gender: Mapped[str] = mapped_column(String(32), default="")
    role: Mapped[str] = mapped_column(String(32), default="user")  # user | owner | admin
    owner_category: Mapped[str] = mapped_column(String(120), default="")  # business type (for owners)
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


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    property_type: Mapped[str] = mapped_column(String(40), default="apartment")  # apartment/house/...
    rent_sale: Mapped[str] = mapped_column(String(10), default="rent")  # rent/sale
    price: Mapped[int] = mapped_column(Integer, default=0)

    location: Mapped[str] = mapped_column(String(255), default="")
    amenities_json: Mapped[str] = mapped_column(Text, default="[]")  # JSON-encoded list of strings

    availability: Mapped[str] = mapped_column(String(40), default="available")
    status: Mapped[str] = mapped_column(String(40), default="pending")  # pending/approved/rejected

    contact_phone: Mapped[str] = mapped_column(String(40), default="")
    contact_email: Mapped[str] = mapped_column(String(255), default="")

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))

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
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))

    property = relationship("Property", back_populates="images")

