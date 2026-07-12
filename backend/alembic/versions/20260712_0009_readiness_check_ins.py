"""Add typed readiness drafts and confirmed check-ins."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260712_0009"
down_revision: str | None = "20260712_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    phase = sa.Enum(
        "POST_RUN",
        "PRE_RUN",
        name="checkinphase",
        native_enum=False,
        create_constraint=True,
        length=16,
    )
    status = sa.Enum(
        "DRAFT",
        "CONFIRMED",
        "CANCELLED",
        "EXPIRED",
        name="checkinstatus",
        native_enum=False,
        create_constraint=True,
        length=16,
    )
    source = sa.Enum(
        "MANUAL",
        "AI_TEXT",
        "AI_VOICE",
        "HEALTH_CONNECT",
        "MERGED",
        name="checkininputsource",
        native_enum=False,
        create_constraint=True,
        length=24,
    )
    op.create_table(
        "readiness_check_ins",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("phase", phase, nullable=False),
        sa.Column("status", status, nullable=False),
        sa.Column("source", source, nullable=False),
        sa.Column("source_confidence", sa.Float()),
        sa.Column("overall_readiness", sa.Integer()),
        sa.Column("general_fatigue", sa.Integer()),
        sa.Column("muscle_soreness", sa.Integer()),
        sa.Column("motivation", sa.Integer()),
        sa.Column("sleep_quality", sa.Integer()),
        sa.Column("sleep_duration_sec", sa.Integer()),
        sa.Column("sleep_ended_at", sa.DateTime(timezone=True)),
        sa.Column("sleep_summary_id", sa.Uuid()),
        sa.Column("external_load", sa.Integer()),
        sa.Column("pain_present", sa.Boolean()),
        sa.Column("pain_severity", sa.Integer()),
        sa.Column("pain_location", sa.String(120)),
        sa.Column("pain_affects_movement", sa.Boolean()),
        sa.Column("pain_is_new", sa.Boolean()),
        sa.Column("pain_is_worsening", sa.Boolean()),
        sa.Column("illness_symptoms", sa.Boolean()),
        sa.Column("available_time_sec", sa.Integer()),
        sa.Column("session_rpe", sa.Integer()),
        sa.Column("linked_activity_id", sa.Uuid()),
        sa.Column("pending_field", sa.String(32)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "overall_readiness IS NULL OR overall_readiness BETWEEN 1 AND 5",
            name=op.f("ck_readiness_check_ins_overall_readiness_range"),
        ),
        sa.CheckConstraint(
            "general_fatigue IS NULL OR general_fatigue BETWEEN 0 AND 10",
            name=op.f("ck_readiness_check_ins_general_fatigue_range"),
        ),
        sa.CheckConstraint(
            "muscle_soreness IS NULL OR muscle_soreness BETWEEN 0 AND 10",
            name=op.f("ck_readiness_check_ins_muscle_soreness_range"),
        ),
        sa.CheckConstraint(
            "motivation IS NULL OR motivation BETWEEN 1 AND 5",
            name=op.f("ck_readiness_check_ins_motivation_range"),
        ),
        sa.CheckConstraint(
            "sleep_quality IS NULL OR sleep_quality BETWEEN 1 AND 5",
            name=op.f("ck_readiness_check_ins_sleep_quality_range"),
        ),
        sa.CheckConstraint(
            "sleep_duration_sec IS NULL OR sleep_duration_sec BETWEEN 1 AND 86400",
            name=op.f("ck_readiness_check_ins_sleep_duration_range"),
        ),
        sa.CheckConstraint(
            "external_load IS NULL OR external_load BETWEEN 0 AND 10",
            name=op.f("ck_readiness_check_ins_external_load_range"),
        ),
        sa.CheckConstraint(
            "pain_severity IS NULL OR pain_severity BETWEEN 0 AND 10",
            name=op.f("ck_readiness_check_ins_pain_severity_range"),
        ),
        sa.CheckConstraint(
            "((pain_present IS NULL) OR (pain_present = false "
            "AND pain_severity IS NULL AND pain_location IS NULL "
            "AND pain_affects_movement IS NULL AND pain_is_new IS NULL "
            "AND pain_is_worsening IS NULL) OR (pain_present = true "
            "AND pain_severity IS NOT NULL AND pain_location IS NOT NULL "
            "AND pain_affects_movement IS NOT NULL AND pain_is_new IS NOT NULL "
            "AND pain_is_worsening IS NOT NULL))",
            name=op.f("ck_readiness_check_ins_pain_fields_consistent"),
        ),
        sa.CheckConstraint(
            "available_time_sec IS NULL OR available_time_sec BETWEEN 1 AND 86400",
            name=op.f("ck_readiness_check_ins_available_time_range"),
        ),
        sa.CheckConstraint(
            "session_rpe IS NULL OR session_rpe BETWEEN 1 AND 10",
            name=op.f("ck_readiness_check_ins_session_rpe_range"),
        ),
        sa.CheckConstraint(
            "phase = 'POST_RUN' OR session_rpe IS NULL",
            name=op.f("ck_readiness_check_ins_session_rpe_post_run_only"),
        ),
        sa.CheckConstraint(
            "source_confidence IS NULL OR source_confidence BETWEEN 0 AND 1",
            name=op.f("ck_readiness_check_ins_source_confidence_range"),
        ),
        sa.CheckConstraint(
            "status != 'CONFIRMED' OR (overall_readiness IS NOT NULL "
            "AND general_fatigue IS NOT NULL AND muscle_soreness IS NOT NULL "
            "AND external_load IS NOT NULL AND pain_present IS NOT NULL "
            "AND illness_symptoms IS NOT NULL)",
            name=op.f("ck_readiness_check_ins_confirmed_required_fields"),
        ),
        sa.ForeignKeyConstraint(["linked_activity_id"], ["activities.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_readiness_check_ins_expires_at", "readiness_check_ins", ["expires_at"])
    op.create_index(
        "uq_readiness_check_ins_active_user_phase",
        "readiness_check_ins",
        ["user_id", "phase"],
        unique=True,
        postgresql_where=sa.text("status = 'DRAFT'"),
        sqlite_where=sa.text("status = 'DRAFT'"),
    )


def downgrade() -> None:
    op.drop_index("uq_readiness_check_ins_active_user_phase", table_name="readiness_check_ins")
    op.drop_index("ix_readiness_check_ins_expires_at", table_name="readiness_check_ins")
    op.drop_table("readiness_check_ins")
