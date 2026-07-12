"""Add operational next-run recommendation revisions."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260712_0010"
down_revision: str | None = "20260712_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    status = sa.Enum(
        "PROVISIONAL",
        "CONFIRMED",
        "SUPERSEDED",
        "EXPIRED",
        "CONSUMED",
        "CANCELLED",
        name="recommendationstatus",
        native_enum=False,
        create_constraint=True,
        length=16,
    )
    op.create_table(
        "next_run_recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("source_activity_id", sa.Uuid()),
        sa.Column("check_in_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("status", status, nullable=False),
        sa.Column("recommended_for", sa.Date(), nullable=False),
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_id", sa.Uuid()),
        sa.Column("inputs_fingerprint", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "valid_until > not_before",
            name=op.f("ck_next_run_recommendations_valid_after_not_before"),
        ),
        sa.ForeignKeyConstraint(["check_in_id"], ["readiness_check_ins.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["goal_id"], ["running_goals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["report_id"], ["coach_reports.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_activity_id"], ["activities.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["supersedes_id"], ["next_run_recommendations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id", name=op.f("uq_next_run_recommendations_report_id")),
        sa.UniqueConstraint("check_in_id", name=op.f("uq_next_run_recommendations_check_in_id")),
    )
    op.create_index(
        "uq_next_run_recommendations_current_user",
        "next_run_recommendations",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('PROVISIONAL', 'CONFIRMED')"),
        sqlite_where=sa.text("status IN ('PROVISIONAL', 'CONFIRMED')"),
    )
    op.create_index(
        "uq_next_run_recommendations_user_idempotency",
        "next_run_recommendations",
        ["user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_next_run_recommendations_user_idempotency",
        table_name="next_run_recommendations",
    )
    op.drop_index(
        "uq_next_run_recommendations_current_user",
        table_name="next_run_recommendations",
    )
    op.drop_table("next_run_recommendations")
