"""Add active running goals."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260712_0008"
down_revision: str | None = "20260711_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    goal_type = sa.Enum(
        "FIRST_5K",
        "FIRST_10K",
        "FIRST_HALF",
        "FIRST_MARATHON",
        "IMPROVE_HALF",
        "IMPROVE_MARATHON",
        "GENERAL_ENDURANCE",
        name="runninggoaltype",
        native_enum=False,
        create_constraint=True,
        length=24,
    )
    status = sa.Enum(
        "ACTIVE",
        "COMPLETED",
        "CANCELLED",
        name="runninggoalstatus",
        native_enum=False,
        create_constraint=True,
        length=16,
    )
    op.create_table(
        "running_goals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("type", goal_type, nullable=False),
        sa.Column("target_date", sa.Date()),
        sa.Column("target_duration_sec", sa.Integer()),
        sa.Column("status", status, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "((type IN ('IMPROVE_HALF', 'IMPROVE_MARATHON') AND "
            "target_duration_sec IS NOT NULL AND target_duration_sec > 0) OR "
            "(type NOT IN ('IMPROVE_HALF', 'IMPROVE_MARATHON') AND "
            "target_duration_sec IS NULL))",
            name=op.f("ck_running_goals_target_duration_matches_type"),
        ),
        sa.CheckConstraint(
            "((status = 'COMPLETED' AND completed_at IS NOT NULL) OR "
            "(status IN ('ACTIVE', 'CANCELLED') AND completed_at IS NULL))",
            name=op.f("ck_running_goals_completed_at_matches_status"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_running_goals_active_user",
        "running_goals",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
        sqlite_where=sa.text("status = 'ACTIVE'"),
    )


def downgrade() -> None:
    op.drop_index("uq_running_goals_active_user", table_name="running_goals")
    op.drop_table("running_goals")
