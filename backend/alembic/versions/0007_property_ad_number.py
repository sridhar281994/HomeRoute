"""property ad_number

Revision ID: 0007_property_ad_number
Revises: 0006_subscription_plans_usage
Create Date: 2026-01-15
"""

from __future__ import annotations

import secrets

from alembic import op
import sqlalchemy as sa


revision = "0007_property_ad_number"
down_revision = "0006_subscription_plans_usage"
branch_labels = None
depends_on = None


_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def _gen() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(6))


def upgrade() -> None:
    # Add nullable column first for safe backfill across DBs.
    with op.batch_alter_table("properties") as batch:
        batch.add_column(sa.Column("ad_number", sa.String(length=6), nullable=True))
        batch.create_index("ix_properties_ad_number", ["ad_number"], unique=True)

    bind = op.get_bind()

    # Backfill existing properties.
    rows = list(bind.execute(sa.text("SELECT id FROM properties")).fetchall())
    used: set[str] = set()
    for (pid,) in rows:
        # generate unique code (avoid collisions within this migration + DB)
        for _ in range(100):
            code = _gen()
            if code in used:
                continue
            existing = bind.execute(sa.text("SELECT 1 FROM properties WHERE ad_number = :c LIMIT 1"), {"c": code}).fetchone()
            if existing:
                continue
            used.add(code)
            bind.execute(sa.text("UPDATE properties SET ad_number = :c WHERE id = :id"), {"c": code, "id": int(pid)})
            break
        else:
            raise RuntimeError("Failed to backfill properties.ad_number")

    with op.batch_alter_table("properties") as batch:
        batch.alter_column("ad_number", existing_type=sa.String(length=6), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("properties") as batch:
        batch.drop_index("ix_properties_ad_number")
        batch.drop_column("ad_number")

