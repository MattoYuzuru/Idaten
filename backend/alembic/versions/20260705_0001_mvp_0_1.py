"""Create MVP 0.1 schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260705_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    source_type = sa.Enum(
        "MANUAL",
        "HEALTH_CONNECT",
        "STRAVA",
        "GPX",
        "FIT",
        "TCX",
        "CSV",
        "SCREENSHOT",
        "SAMSUNG_EXPORT",
        name="sourcetype",
        native_enum=False,
        create_constraint=True,
        length=32,
    )
    source_status = sa.Enum(
        "ACTIVE",
        "DISABLED",
        "ERROR",
        name="sourcestatus",
        native_enum=False,
        create_constraint=True,
        length=16,
    )
    activity_type = sa.Enum(
        "RUN",
        "WALK",
        "BIKE",
        "OTHER",
        name="activitytype",
        native_enum=False,
        create_constraint=True,
        length=16,
    )
    visibility = sa.Enum(
        "PRIVATE",
        "GROUP_SUMMARY",
        "GROUP_DETAILED",
        "PUBLIC",
        name="activityvisibility",
        native_enum=False,
        create_constraint=True,
        length=24,
    )
    report_type = sa.Enum(
        "AFTER_RUN",
        "WEEKLY",
        "MONTHLY",
        "PLAN",
        "NEXT_WORKOUT",
        name="reporttype",
        native_enum=False,
        create_constraint=True,
        length=24,
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_table(
        "telegram_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("first_name", sa.String(255), nullable=False),
        sa.Column("last_name", sa.String(255), nullable=True),
        sa.Column("private_chat_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_telegram_accounts_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_telegram_accounts"),
    )
    op.create_index(
        "ix_telegram_accounts_telegram_user_id",
        "telegram_accounts",
        ["telegram_user_id"],
        unique=True,
    )
    op.create_index("ix_telegram_accounts_user_id", "telegram_accounts", ["user_id"], unique=True)

    op.create_table(
        "activity_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", source_type, nullable=False),
        sa.Column("status", source_status, nullable=False),
        sa.Column("external_account_id", sa.String(255), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_activity_sources_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_activity_sources"),
        sa.UniqueConstraint("user_id", "source_type", name="uq_activity_sources_user_source"),
    )

    op.create_table(
        "activities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", source_type, nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("activity_type", activity_type, nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("distance_m", sa.Integer(), nullable=False),
        sa.Column("elapsed_time_sec", sa.Integer(), nullable=False),
        sa.Column("moving_time_sec", sa.Integer(), nullable=True),
        sa.Column("avg_pace_sec_per_km", sa.Integer(), nullable=False),
        sa.Column("avg_speed_mps", sa.Float(), nullable=False),
        sa.Column("avg_hr", sa.Integer(), nullable=True),
        sa.Column("max_hr", sa.Integer(), nullable=True),
        sa.Column("visibility", visibility, nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("distance_m > 0", name="ck_activities_distance_positive"),
        sa.CheckConstraint("elapsed_time_sec > 0", name="ck_activities_elapsed_positive"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["activity_sources.id"],
            name="fk_activities_source_id_activity_sources",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_activities_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_activities"),
    )
    op.create_index("ix_activities_user_started_at", "activities", ["user_id", "started_at"])
    op.create_index(
        "uq_activities_source_external_id",
        "activities",
        ["source_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )

    op.create_table(
        "coach_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("activity_id", sa.Uuid(), nullable=True),
        sa.Column("report_type", report_type, nullable=False),
        sa.Column("facts_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rule_result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("message_private", sa.Text(), nullable=False),
        sa.Column("message_group", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["activities.id"],
            name="fk_coach_reports_activity_id_activities",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_coach_reports_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_coach_reports"),
        sa.UniqueConstraint("activity_id", name="uq_coach_reports_activity_id"),
    )


def downgrade() -> None:
    op.drop_table("coach_reports")
    op.drop_index("uq_activities_source_external_id", table_name="activities")
    op.drop_index("ix_activities_user_started_at", table_name="activities")
    op.drop_table("activities")
    op.drop_table("activity_sources")
    op.drop_index("ix_telegram_accounts_user_id", table_name="telegram_accounts")
    op.drop_index("ix_telegram_accounts_telegram_user_id", table_name="telegram_accounts")
    op.drop_table("telegram_accounts")
    op.drop_table("users")
