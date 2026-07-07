"""Add Health Connect devices, secure linking, sync status, and Telegram outbox."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260706_0004"
down_revision: str | None = "20260706_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    device_scope = sa.Enum(
        "HEALTH_CONNECT_SYNC",
        "STATUS_ONLY",
        name="devicescope",
        native_enum=False,
        create_constraint=True,
        length=32,
    )
    sync_status = sa.Enum(
        "NEVER",
        "SUCCESS",
        "PARTIAL",
        "FAILED",
        name="syncstatus",
        native_enum=False,
        create_constraint=True,
        length=16,
    )
    outbox_status = sa.Enum(
        "PENDING",
        "PROCESSING",
        "DELIVERED",
        "FAILED",
        name="outboxstatus",
        native_enum=False,
        create_constraint=True,
        length=16,
    )
    op.create_table(
        "device_link_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_device_link_codes_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_device_link_codes"),
        sa.UniqueConstraint("code_hash", name="uq_device_link_codes_code_hash"),
    )
    op.create_index("ix_device_link_codes_expires_at", "device_link_codes", ["expires_at"])
    op.create_table(
        "device_link_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("attempt_key_hash", sa.String(64), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_device_link_attempts"),
    )
    op.create_index(
        "ix_device_link_attempts_key_time",
        "device_link_attempts",
        ["attempt_key_hash", "attempted_at"],
    )
    op.create_table(
        "devices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("installation_id_hash", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("token_scope", device_scope, nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_cursor", sa.String(255), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sync_status, nullable=False),
        sa.Column("last_sync_error", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_devices_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_devices"),
        sa.UniqueConstraint("token_hash", name="uq_devices_token_hash"),
        sa.UniqueConstraint("user_id", "installation_id_hash", name="uq_devices_user_installation"),
    )
    op.create_index("ix_devices_revoked_at", "devices", ["revoked_at"])
    op.create_table(
        "telegram_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("private_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_text", sa.String(4096), nullable=False),
        sa.Column("status", outbox_status, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["activities.id"],
            name="fk_telegram_outbox_activity_id_activities",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_telegram_outbox_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_telegram_outbox"),
        sa.UniqueConstraint("activity_id", name="uq_telegram_outbox_activity_id"),
    )
    op.create_index("ix_telegram_outbox_status", "telegram_outbox", ["status"])
    op.create_index("ix_telegram_outbox_available_at", "telegram_outbox", ["available_at"])


def downgrade() -> None:
    op.drop_index("ix_telegram_outbox_available_at", table_name="telegram_outbox")
    op.drop_index("ix_telegram_outbox_status", table_name="telegram_outbox")
    op.drop_table("telegram_outbox")
    op.drop_index("ix_devices_revoked_at", table_name="devices")
    op.drop_table("devices")
    op.drop_index("ix_device_link_attempts_key_time", table_name="device_link_attempts")
    op.drop_table("device_link_attempts")
    op.drop_index("ix_device_link_codes_expires_at", table_name="device_link_codes")
    op.drop_table("device_link_codes")
