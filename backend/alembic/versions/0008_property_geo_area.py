"""property geo + area

Revision ID: 0008_property_geo_area
Revises: 0007_property_ad_number
Create Date: 2026-01-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_property_geo_area"
down_revision = "0007_property_ad_number"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add columns nullable first for safe backfill across DBs.
    with op.batch_alter_table("properties") as batch:
        batch.add_column(sa.Column("area", sa.String(length=160), nullable=True))
        batch.add_column(sa.Column("area_normalized", sa.String(length=160), nullable=True))
        batch.add_column(sa.Column("gps_lat", sa.Float(), nullable=True))
        batch.add_column(sa.Column("gps_lng", sa.Float(), nullable=True))
        batch.create_index("ix_properties_area", ["area"], unique=False)
        batch.create_index("ix_properties_area_normalized", ["area_normalized"], unique=False)
        batch.create_index("ix_properties_gps_lat", ["gps_lat"], unique=False)
        batch.create_index("ix_properties_gps_lng", ["gps_lng"], unique=False)

    bind = op.get_bind()
    # Backfill text fields for existing rows.
    bind.execute(sa.text("UPDATE properties SET area = COALESCE(area, '')"))
    bind.execute(sa.text("UPDATE properties SET area_normalized = COALESCE(area_normalized, '')"))

    with op.batch_alter_table("properties") as batch:
        batch.alter_column("area", existing_type=sa.String(length=160), nullable=False)
        batch.alter_column("area_normalized", existing_type=sa.String(length=160), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("properties") as batch:
        batch.drop_index("ix_properties_gps_lng")
        batch.drop_index("ix_properties_gps_lat")
        batch.drop_index("ix_properties_area_normalized")
        batch.drop_index("ix_properties_area")
        batch.drop_column("gps_lng")
        batch.drop_column("gps_lat")
        batch.drop_column("area_normalized")
        batch.drop_column("area")

