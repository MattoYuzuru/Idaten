"""Add optional Health Connect sleep summaries."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260712_0012"
down_revision: str | None = "20260712_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "health_connect_sleep_summaries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("duration_sec", sa.Integer()),
        sa.Column("sleep_quality", sa.Integer()),
        sa.Column("data_origin", sa.String(255)),
        sa.Column("observed_at", sa.DateTime(timezone=True)),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "duration_sec IS NULL OR duration_sec BETWEEN 1 AND 86400",
            name=op.f("ck_health_connect_sleep_summaries_duration_range"),
        ),
        sa.CheckConstraint(
            "sleep_quality IS NULL OR sleep_quality BETWEEN 1 AND 5",
            name=op.f("ck_health_connect_sleep_summaries_quality_range"),
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR ended_at IS NULL OR ended_at > started_at",
            name=op.f("ck_health_connect_sleep_summaries_positive_interval"),
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name=op.f("fk_health_connect_sleep_summaries_device_id_devices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_health_connect_sleep_summaries_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_health_connect_sleep_summaries")),
        sa.UniqueConstraint(
            "device_id",
            "external_id",
            name=op.f("uq_health_connect_sleep_summaries_device_external"),
        ),
    )
    op.create_index(
        "ix_health_connect_sleep_user_end",
        "health_connect_sleep_summaries",
        ["user_id", "ended_at"],
    )
    op.create_foreign_key(
        op.f("fk_readiness_check_ins_sleep_summary_id_health_connect_sleep_summaries"),
        "readiness_check_ins",
        "health_connect_sleep_summaries",
        ["sleep_summary_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        op.f("ck_readiness_check_ins_sleep_provenance_complete"),
        "readiness_check_ins",
        "sleep_summary_id IS NULL OR "
        "(sleep_duration_sec IS NOT NULL AND sleep_ended_at IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_readiness_check_ins_sleep_provenance_complete"),
        "readiness_check_ins",
        type_="check",
    )
    op.drop_constraint(
        op.f("fk_readiness_check_ins_sleep_summary_id_health_connect_sleep_summaries"),
        "readiness_check_ins",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_health_connect_sleep_user_end",
        table_name="health_connect_sleep_summaries",
    )
    op.drop_table("health_connect_sleep_summaries")
