"""Add guided manual drafts, activity aggregates, and batch sync summaries."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260708_0006"
down_revision: str | None = "20260707_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("activities", sa.Column("avg_cadence_spm", sa.Integer(), nullable=True))
    op.add_column("activities", sa.Column("elevation_gain_m", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_activities_avg_cadence_range",
        "activities",
        "avg_cadence_spm IS NULL OR (avg_cadence_spm >= 30 AND avg_cadence_spm <= 300)",
    )
    op.create_check_constraint(
        "ck_activities_elevation_gain_range",
        "activities",
        "elevation_gain_m IS NULL OR (elevation_gain_m >= 0 AND elevation_gain_m <= 20000)",
    )

    draft_status = sa.Enum(
        "ACTIVE",
        "SAVED",
        "CANCELLED",
        "EXPIRED",
        name="manualdraftstatus",
        native_enum=False,
        create_constraint=True,
        length=16,
    )
    op.create_table(
        "manual_activity_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", draft_status, nullable=False),
        sa.Column("distance_m", sa.Integer(), nullable=True),
        sa.Column("elapsed_time_sec", sa.Integer(), nullable=True),
        sa.Column("moving_time_sec", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("avg_hr", sa.Integer(), nullable=True),
        sa.Column("max_hr", sa.Integer(), nullable=True),
        sa.Column("avg_cadence_spm", sa.Integer(), nullable=True),
        sa.Column("elevation_gain_m", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("pending_field", sa.String(32), nullable=True),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("activity_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "distance_m IS NULL OR distance_m > 0",
            name="ck_manual_activity_drafts_distance_positive",
        ),
        sa.CheckConstraint(
            "elapsed_time_sec IS NULL OR elapsed_time_sec > 0",
            name="ck_manual_activity_drafts_elapsed_positive",
        ),
        sa.CheckConstraint(
            "moving_time_sec IS NULL OR elapsed_time_sec IS NULL OR "
            "moving_time_sec <= elapsed_time_sec",
            name="ck_manual_activity_drafts_moving_not_greater_than_elapsed",
        ),
        sa.CheckConstraint(
            "avg_cadence_spm IS NULL OR (avg_cadence_spm >= 30 AND avg_cadence_spm <= 300)",
            name="ck_manual_activity_drafts_avg_cadence_range",
        ),
        sa.CheckConstraint(
            "elevation_gain_m IS NULL OR (elevation_gain_m >= 0 AND elevation_gain_m <= 20000)",
            name="ck_manual_activity_drafts_elevation_gain_range",
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["activities.id"],
            name="fk_manual_activity_drafts_activity_id_activities",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_manual_activity_drafts_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_manual_activity_drafts"),
    )
    op.create_index(
        "ix_manual_activity_drafts_expires_at", "manual_activity_drafts", ["expires_at"]
    )
    op.create_index(
        "uq_manual_activity_drafts_active_user",
        "manual_activity_drafts",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
        sqlite_where=sa.text("status = 'ACTIVE'"),
    )

    op.create_table(
        "health_connect_sync_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("batch_key", sa.String(64), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("found_count", sa.Integer(), nullable=False),
        sa.Column("saved_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name="fk_health_connect_sync_batches_device_id_devices",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_health_connect_sync_batches_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_health_connect_sync_batches"),
        sa.UniqueConstraint("batch_key", name="uq_health_connect_sync_batches_batch_key"),
    )
    op.create_index(
        "ix_health_connect_sync_batches_created_at", "health_connect_sync_batches", ["created_at"]
    )
    op.alter_column("telegram_outbox", "activity_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("telegram_outbox", sa.Column("batch_id", sa.Uuid(), nullable=True))
    op.add_column("telegram_outbox", sa.Column("event_key", sa.String(128), nullable=True))
    op.create_foreign_key(
        "fk_telegram_outbox_batch_id_health_connect_sync_batches",
        "telegram_outbox",
        "health_connect_sync_batches",
        ["batch_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint("uq_telegram_outbox_batch_id", "telegram_outbox", ["batch_id"])
    op.create_unique_constraint("uq_telegram_outbox_event_key", "telegram_outbox", ["event_key"])
    op.create_check_constraint(
        "ck_telegram_outbox_exactly_one_subject",
        "telegram_outbox",
        "(CASE WHEN activity_id IS NOT NULL THEN 1 ELSE 0 END + "
        "CASE WHEN batch_id IS NOT NULL THEN 1 ELSE 0 END + "
        "CASE WHEN event_key IS NOT NULL THEN 1 ELSE 0 END) = 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_telegram_outbox_exactly_one_subject", "telegram_outbox", type_="check")
    op.drop_constraint("uq_telegram_outbox_event_key", "telegram_outbox", type_="unique")
    op.drop_constraint("uq_telegram_outbox_batch_id", "telegram_outbox", type_="unique")
    op.drop_constraint(
        "fk_telegram_outbox_batch_id_health_connect_sync_batches",
        "telegram_outbox",
        type_="foreignkey",
    )
    op.execute("DELETE FROM telegram_outbox WHERE batch_id IS NOT NULL OR event_key IS NOT NULL")
    op.drop_column("telegram_outbox", "event_key")
    op.drop_column("telegram_outbox", "batch_id")
    op.alter_column("telegram_outbox", "activity_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_index(
        "ix_health_connect_sync_batches_created_at", table_name="health_connect_sync_batches"
    )
    op.drop_table("health_connect_sync_batches")
    op.drop_index("uq_manual_activity_drafts_active_user", table_name="manual_activity_drafts")
    op.drop_index("ix_manual_activity_drafts_expires_at", table_name="manual_activity_drafts")
    op.drop_table("manual_activity_drafts")
    op.drop_constraint("ck_activities_elevation_gain_range", "activities", type_="check")
    op.drop_constraint("ck_activities_avg_cadence_range", "activities", type_="check")
    op.drop_column("activities", "elevation_gain_m")
    op.drop_column("activities", "avg_cadence_spm")
