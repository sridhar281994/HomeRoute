"""initial schema (users, properties, subscriptions, images)

Revision ID: 0001_initial
Revises: 
Create Date: 2026-01-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("state", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("gender", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="user"),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_username", "users", ["username"])

    op.create_table(
        "otp_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("identifier", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("code", sa.String(length=12), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_otp_codes_identifier", "otp_codes", ["identifier"])
    op.create_index("ix_otp_codes_purpose", "otp_codes", ["purpose"])

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False, server_default="google_play"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="inactive"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purchase_token", sa.String(length=255), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", name="uq_subscriptions_user_id"),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])

    op.create_table(
        "properties",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("property_type", sa.String(length=40), nullable=False, server_default="apartment"),
        sa.Column("rent_sale", sa.String(length=10), nullable=False, server_default="rent"),
        sa.Column("price", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("location", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("amenities_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("availability", sa.String(length=40), nullable=False, server_default="available"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("contact_phone", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("contact_email", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_properties_owner_id", "properties", ["owner_id"])

    op.create_table(
        "saved_properties",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "property_id", name="uq_saved_user_property"),
    )
    op.create_index("ix_saved_properties_user_id", "saved_properties", ["user_id"])
    op.create_index("ix_saved_properties_property_id", "saved_properties", ["property_id"])

    op.create_table(
        "property_images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("property_id", "sort_order", name="uq_property_image_sort"),
    )
    op.create_index("ix_property_images_property_id", "property_images", ["property_id"])


def downgrade() -> None:
    op.drop_index("ix_property_images_property_id", table_name="property_images")
    op.drop_table("property_images")

    op.drop_index("ix_saved_properties_property_id", table_name="saved_properties")
    op.drop_index("ix_saved_properties_user_id", table_name="saved_properties")
    op.drop_table("saved_properties")

    op.drop_index("ix_properties_owner_id", table_name="properties")
    op.drop_table("properties")

    op.drop_index("ix_subscriptions_user_id", table_name="subscriptions")
    op.drop_table("subscriptions")

    op.drop_index("ix_otp_codes_purpose", table_name="otp_codes")
    op.drop_index("ix_otp_codes_identifier", table_name="otp_codes")
    op.drop_table("otp_codes")

    op.drop_index("ix_users_username", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

