"""add user profile image

Revision ID: 0005_user_profile_image
Revises: 0004_admin_approval_images
Create Date: 2026-01-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_user_profile_image"
down_revision = "0004_admin_approval_images"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("profile_image_path", sa.String(length=512), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("users", "profile_image_path")

