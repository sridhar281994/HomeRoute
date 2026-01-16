"""free contact usage tracking

Revision ID: 0009_free_contact_usage
Revises: 0008_property_geo_area
Create Date: 2026-01-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_free_contact_usage"
down_revision = "0008_property_geo_area"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "free_contact_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "property_id", name="uq_free_usage_user_property"),
    )
    op.create_index("ix_free_contact_usage_user_id", "free_contact_usage", ["user_id"], unique=False)
    op.create_index("ix_free_contact_usage_property_id", "free_contact_usage", ["property_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_free_contact_usage_property_id", table_name="free_contact_usage")
    op.drop_index("ix_free_contact_usage_user_id", table_name="free_contact_usage")
    op.drop_table("free_contact_usage")

