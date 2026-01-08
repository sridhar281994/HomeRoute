"""add district to users

Revision ID: 0002_add_user_district
Revises: 0001_initial
Create Date: 2026-01-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_add_user_district"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("district", sa.String(length=120), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("users", "district")

