"""cloudinary public ids for media cleanup

Revision ID: 0011_cloudinary_public_ids
Revises: 0010_user_gps_coords
Create Date: 2026-01-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0011_cloudinary_public_ids"
down_revision = "0010_user_gps_coords"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite-safe via batch_alter_table.
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("profile_image_cloudinary_public_id", sa.String(length=255), nullable=False, server_default=""))

    with op.batch_alter_table("property_images") as batch:
        batch.add_column(sa.Column("cloudinary_public_id", sa.String(length=255), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("property_images") as batch:
        batch.drop_column("cloudinary_public_id")

    with op.batch_alter_table("users") as batch:
        batch.drop_column("profile_image_cloudinary_public_id")

