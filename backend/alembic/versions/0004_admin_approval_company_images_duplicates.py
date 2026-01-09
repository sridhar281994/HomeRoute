"""admin approval + company profile + image hash + duplicate prevention

Revision ID: 0004_admin_approval_company_images_duplicates
Revises: 0003_add_user_phone_and_owner_category
Create Date: 2026-01-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_admin_approval_company_images_duplicates"
down_revision = "0003_add_user_phone_and_owner_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- users ----
    op.add_column("users", sa.Column("phone_normalized", sa.String(length=32), nullable=False, server_default=""))
    op.add_column("users", sa.Column("company_name", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("users", sa.Column("company_name_normalized", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("users", sa.Column("company_description", sa.Text(), nullable=False, server_default=""))
    op.add_column("users", sa.Column("company_address", sa.String(length=512), nullable=False, server_default=""))
    op.add_column("users", sa.Column("company_address_normalized", sa.String(length=512), nullable=False, server_default=""))
    op.add_column("users", sa.Column("approval_status", sa.String(length=40), nullable=False, server_default="approved"))
    op.add_column("users", sa.Column("approval_reason", sa.Text(), nullable=False, server_default=""))

    op.create_index("ix_users_phone_normalized", "users", ["phone_normalized"], unique=False)
    op.create_index("ix_users_company_name", "users", ["company_name"], unique=False)
    op.create_index("ix_users_company_name_normalized", "users", ["company_name_normalized"], unique=False)
    op.create_index("ix_users_company_address", "users", ["company_address"], unique=False)
    op.create_index("ix_users_company_address_normalized", "users", ["company_address_normalized"], unique=False)
    op.create_index("ix_users_approval_status", "users", ["approval_status"], unique=False)

    # Enforce uniqueness while allowing empty-string placeholders.
    op.create_index(
        "uq_users_phone_normalized_not_empty",
        "users",
        ["phone_normalized"],
        unique=True,
        postgresql_where=sa.text("phone_normalized <> ''"),
    )
    op.create_index(
        "uq_users_company_name_normalized_not_empty",
        "users",
        ["company_name_normalized"],
        unique=True,
        postgresql_where=sa.text("company_name_normalized <> ''"),
    )

    # ---- properties ----
    op.add_column("properties", sa.Column("address", sa.String(length=512), nullable=False, server_default=""))
    op.add_column("properties", sa.Column("address_normalized", sa.String(length=512), nullable=False, server_default=""))
    op.add_column("properties", sa.Column("state", sa.String(length=80), nullable=False, server_default=""))
    op.add_column("properties", sa.Column("district", sa.String(length=120), nullable=False, server_default=""))
    op.add_column("properties", sa.Column("state_normalized", sa.String(length=80), nullable=False, server_default=""))
    op.add_column("properties", sa.Column("district_normalized", sa.String(length=120), nullable=False, server_default=""))
    op.add_column("properties", sa.Column("moderation_reason", sa.Text(), nullable=False, server_default=""))
    op.add_column("properties", sa.Column("contact_phone_normalized", sa.String(length=40), nullable=False, server_default=""))
    op.add_column("properties", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    op.add_column("properties", sa.Column("allow_duplicate_address", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("properties", sa.Column("allow_duplicate_phone", sa.Boolean(), nullable=False, server_default=sa.text("false")))

    op.create_index("ix_properties_address_normalized", "properties", ["address_normalized"], unique=False)
    op.create_index("ix_properties_state", "properties", ["state"], unique=False)
    op.create_index("ix_properties_district", "properties", ["district"], unique=False)
    op.create_index("ix_properties_state_normalized", "properties", ["state_normalized"], unique=False)
    op.create_index("ix_properties_district_normalized", "properties", ["district_normalized"], unique=False)
    op.create_index("ix_properties_contact_phone_normalized", "properties", ["contact_phone_normalized"], unique=False)

    # Duplicate-prevention constraints (admin can override via allow_duplicate_* flags).
    op.create_index(
        "uq_properties_address_normalized_no_override",
        "properties",
        ["address_normalized"],
        unique=True,
        postgresql_where=sa.text("address_normalized <> '' AND allow_duplicate_address = false"),
    )
    op.create_index(
        "uq_properties_contact_phone_normalized_no_override",
        "properties",
        ["contact_phone_normalized"],
        unique=True,
        postgresql_where=sa.text("contact_phone_normalized <> '' AND allow_duplicate_phone = false"),
    )

    # ---- property_images ----
    op.add_column("property_images", sa.Column("image_hash", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("property_images", sa.Column("original_filename", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("property_images", sa.Column("content_type", sa.String(length=100), nullable=False, server_default=""))
    op.add_column("property_images", sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("property_images", sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"))
    op.add_column("property_images", sa.Column("moderation_reason", sa.Text(), nullable=False, server_default=""))
    op.add_column("property_images", sa.Column("uploaded_by_user_id", sa.Integer(), nullable=True))

    op.create_index("ix_property_images_image_hash", "property_images", ["image_hash"], unique=False)
    op.create_index("ix_property_images_status", "property_images", ["status"], unique=False)
    op.create_index("ix_property_images_uploaded_by_user_id", "property_images", ["uploaded_by_user_id"], unique=False)
    op.create_index(
        "uq_property_images_image_hash_not_empty",
        "property_images",
        ["image_hash"],
        unique=True,
        postgresql_where=sa.text("image_hash <> ''"),
    )
    op.create_foreign_key(
        "fk_property_images_uploaded_by_user_id_users",
        "property_images",
        "users",
        ["uploaded_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ---- moderation_logs ----
    op.create_table(
        "moderation_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_moderation_logs_actor_user_id", "moderation_logs", ["actor_user_id"], unique=False)
    op.create_index("ix_moderation_logs_entity_type", "moderation_logs", ["entity_type"], unique=False)
    op.create_index("ix_moderation_logs_entity_id", "moderation_logs", ["entity_id"], unique=False)
    op.create_index("ix_moderation_logs_action", "moderation_logs", ["action"], unique=False)


def downgrade() -> None:
    # moderation_logs
    op.drop_index("ix_moderation_logs_action", table_name="moderation_logs")
    op.drop_index("ix_moderation_logs_entity_id", table_name="moderation_logs")
    op.drop_index("ix_moderation_logs_entity_type", table_name="moderation_logs")
    op.drop_index("ix_moderation_logs_actor_user_id", table_name="moderation_logs")
    op.drop_table("moderation_logs")

    # property_images
    op.drop_constraint("fk_property_images_uploaded_by_user_id_users", "property_images", type_="foreignkey")
    op.drop_index("uq_property_images_image_hash_not_empty", table_name="property_images")
    op.drop_index("ix_property_images_uploaded_by_user_id", table_name="property_images")
    op.drop_index("ix_property_images_status", table_name="property_images")
    op.drop_index("ix_property_images_image_hash", table_name="property_images")
    op.drop_column("property_images", "uploaded_by_user_id")
    op.drop_column("property_images", "moderation_reason")
    op.drop_column("property_images", "status")
    op.drop_column("property_images", "size_bytes")
    op.drop_column("property_images", "content_type")
    op.drop_column("property_images", "original_filename")
    op.drop_column("property_images", "image_hash")

    # properties
    op.drop_index("uq_properties_contact_phone_normalized_no_override", table_name="properties")
    op.drop_index("uq_properties_address_normalized_no_override", table_name="properties")
    op.drop_index("ix_properties_contact_phone_normalized", table_name="properties")
    op.drop_index("ix_properties_district_normalized", table_name="properties")
    op.drop_index("ix_properties_state_normalized", table_name="properties")
    op.drop_index("ix_properties_district", table_name="properties")
    op.drop_index("ix_properties_state", table_name="properties")
    op.drop_index("ix_properties_address_normalized", table_name="properties")
    op.drop_column("properties", "allow_duplicate_phone")
    op.drop_column("properties", "allow_duplicate_address")
    op.drop_column("properties", "updated_at")
    op.drop_column("properties", "contact_phone_normalized")
    op.drop_column("properties", "moderation_reason")
    op.drop_column("properties", "district_normalized")
    op.drop_column("properties", "state_normalized")
    op.drop_column("properties", "district")
    op.drop_column("properties", "state")
    op.drop_column("properties", "address_normalized")
    op.drop_column("properties", "address")

    # users
    op.drop_index("uq_users_company_name_normalized_not_empty", table_name="users")
    op.drop_index("uq_users_phone_normalized_not_empty", table_name="users")
    op.drop_index("ix_users_approval_status", table_name="users")
    op.drop_index("ix_users_company_address_normalized", table_name="users")
    op.drop_index("ix_users_company_address", table_name="users")
    op.drop_index("ix_users_company_name_normalized", table_name="users")
    op.drop_index("ix_users_company_name", table_name="users")
    op.drop_index("ix_users_phone_normalized", table_name="users")
    op.drop_column("users", "approval_reason")
    op.drop_column("users", "approval_status")
    op.drop_column("users", "company_address_normalized")
    op.drop_column("users", "company_address")
    op.drop_column("users", "company_description")
    op.drop_column("users", "company_name_normalized")
    op.drop_column("users", "company_name")
    op.drop_column("users", "phone_normalized")

