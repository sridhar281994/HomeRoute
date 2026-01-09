"""add phone and owner category to users

Revision ID: 0003_add_user_phone_owner_cat
Revises: 0002_add_user_district
Create Date: 2026-01-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_add_user_phone_owner_cat"
down_revision = "0002_add_user_district"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("phone", sa.String(length=20), nullable=False, server_default=""))
    op.add_column("users", sa.Column("owner_category", sa.String(length=120), nullable=False, server_default=""))
    op.create_index("ix_users_phone", "users", ["phone"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_phone", table_name="users")
    op.drop_column("users", "owner_category")
    op.drop_column("users", "phone")

