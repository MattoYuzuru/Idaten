"""Add versioned coach plans, provider consent, and monthly report outbox."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260707_0005"
down_revision: str | None = "20260706_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "external_processing_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "coach_reports",
        sa.Column("provider", sa.String(32), server_default="NONE", nullable=False),
    )
    op.add_column("coach_reports", sa.Column("provider_model", sa.String(128)))
    op.add_column("coach_reports", sa.Column("prompt_hash", sa.String(64)))

    goal = sa.Enum(
        "FIRST_10K",
        "HALF",
        "MARATHON",
        "CUSTOM",
        name="traininggoal",
        native_enum=False,
        create_constraint=True,
        length=16,
    )
    status = sa.Enum(
        "DRAFT",
        "ACTIVE",
        "COMPLETED",
        name="planstatus",
        native_enum=False,
        create_constraint=True,
        length=16,
    )
    outbox_status = sa.Enum(
        "PENDING",
        "PROCESSING",
        "DELIVERED",
        "FAILED",
        name="monthlyoutboxstatus",
        native_enum=False,
        create_constraint=True,
        length=16,
    )
    op.create_table(
        "training_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("goal", goal, nullable=False),
        sa.Column("custom_goal", sa.String(255)),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("weeks", sa.Integer(), nullable=False),
        sa.Column("baseline_weekly_distance_m", sa.Integer(), nullable=False),
        sa.Column("calculator_version", sa.String(32), nullable=False),
        sa.Column("rule_version", sa.String(32), nullable=False),
        sa.Column("status", status, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "starts_on", name="uq_training_plans_user_start"),
    )
    op.create_table(
        "planned_workouts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("week_index", sa.Integer(), nullable=False),
        sa.Column("scheduled_for", sa.Date(), nullable=False),
        sa.Column("workout_type", sa.String(24), nullable=False),
        sa.Column("distance_m", sa.Integer(), nullable=False),
        sa.Column("duration_sec", sa.Integer(), nullable=False),
        sa.Column("pace_min_sec_per_km", sa.Integer()),
        sa.Column("pace_max_sec_per_km", sa.Integer()),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("risk_flags", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["training_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "week_index", name="uq_planned_workouts_plan_week"),
    )
    op.create_index("ix_planned_workouts_plan_id", "planned_workouts", ["plan_id"])
    op.create_table(
        "group_goals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("target_distance_m", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["running_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "period_start", name="uq_group_goals_group_period"),
    )
    op.create_index("ix_group_goals_group_id", "group_goals", ["group_id"])
    op.create_table(
        "group_monthly_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("report_type", sa.String(16), server_default="MONTHLY", nullable=False),
        sa.Column("facts_json", sa.JSON(), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["running_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "group_id", "period_start", "report_type", name="uq_group_monthly_report_period"
        ),
    )
    op.create_index("ix_group_monthly_reports_group_id", "group_monthly_reports", ["group_id"])
    op.create_table(
        "group_report_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("status", outbox_status, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("telegram_message_id", sa.BigInteger()),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["group_monthly_reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id"),
    )
    op.create_index("ix_group_report_outbox_status", "group_report_outbox", ["status"])
    op.create_index("ix_group_report_outbox_available_at", "group_report_outbox", ["available_at"])


def downgrade() -> None:
    op.drop_index("ix_group_report_outbox_available_at", table_name="group_report_outbox")
    op.drop_index("ix_group_report_outbox_status", table_name="group_report_outbox")
    op.drop_table("group_report_outbox")
    op.drop_index("ix_group_monthly_reports_group_id", table_name="group_monthly_reports")
    op.drop_table("group_monthly_reports")
    op.drop_index("ix_group_goals_group_id", table_name="group_goals")
    op.drop_table("group_goals")
    op.drop_index("ix_planned_workouts_plan_id", table_name="planned_workouts")
    op.drop_table("planned_workouts")
    op.drop_table("training_plans")
    op.drop_column("coach_reports", "prompt_hash")
    op.drop_column("coach_reports", "provider_model")
    op.drop_column("coach_reports", "provider")
    op.drop_column("users", "external_processing_enabled")
