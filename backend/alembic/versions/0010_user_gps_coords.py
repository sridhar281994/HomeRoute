"""add user gps coords

Revision ID: 0010_user_gps_coords
Revises: 0009_free_contact_usage
Create Date: 2026-01-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0010_user_gps_coords"
down_revision = "0009_free_contact_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("gps_lat", sa.Float(), nullable=True))
        batch.add_column(sa.Column("gps_lng", sa.Float(), nullable=True))
        batch.create_index("ix_users_gps_lat", ["gps_lat"], unique=False)
        batch.create_index("ix_users_gps_lng", ["gps_lng"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_gps_lng")
        batch.drop_index("ix_users_gps_lat")
        batch.drop_column("gps_lng")
        batch.drop_column("gps_lat")
