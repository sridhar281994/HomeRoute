"""subscription plans + usage tracking

Revision ID: 0006_subscription_plans_usage
Revises: 0005_user_profile_image
Create Date: 2026-01-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_subscription_plans_usage"
down_revision = "0005_user_profile_image"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription_plans",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("price_inr", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("contact_limit", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "user_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("plan_id", sa.String(length=80), sa.ForeignKey("subscription_plans.id"), nullable=False, index=True),
        sa.Column("purchase_token", sa.String(length=255), nullable=False, unique=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "contact_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=False, index=True),
        sa.Column("subscription_id", sa.Integer(), sa.ForeignKey("user_subscriptions.id"), nullable=False, index=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("user_id", "property_id", "subscription_id", name="uq_usage_user_property_sub"),
    )


def downgrade() -> None:
    op.drop_table("contact_usage")
    op.drop_table("user_subscriptions")
    op.drop_table("subscription_plans")

