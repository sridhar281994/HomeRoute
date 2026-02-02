"""add properties.post_group for services/property filtering

Revision ID: 0012_property_post_group
Revises: 0011_cloudinary_public_ids
Create Date: 2026-02-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0012_property_post_group"
down_revision = "0011_cloudinary_public_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite-safe via batch_alter_table.
    with op.batch_alter_table("properties") as batch:
        batch.add_column(sa.Column("post_group", sa.String(length=40), nullable=False, server_default=""))

    op.create_index("ix_properties_post_group", "properties", ["post_group"])


def downgrade() -> None:
    op.drop_index("ix_properties_post_group", table_name="properties")
    with op.batch_alter_table("properties") as batch:
        batch.drop_column("post_group")

