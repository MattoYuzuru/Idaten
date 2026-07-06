"""Add file ingestion artifacts, imports, splits, and series."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260706_0003"
down_revision: str | None = "20260706_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    import_status = sa.Enum(
        "RECEIVED",
        "PREVIEW",
        "CONFIRMED",
        "DUPLICATE",
        "FAILED",
        "CANCELLED",
        name="importstatus",
        native_enum=False,
        create_constraint=True,
        length=16,
    )
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

    op.create_table(
        "raw_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("storage_uri", sa.String(512), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(127), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_raw_artifacts_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_raw_artifacts"),
        sa.UniqueConstraint("storage_uri", name="uq_raw_artifacts_storage_uri"),
        sa.UniqueConstraint("user_id", "sha256", name="uq_raw_artifacts_user_sha256"),
    )
    op.create_table(
        "imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("raw_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("status", import_status, nullable=False),
        sa.Column("source_type", source_type, nullable=True),
        sa.Column("normalized_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("draft_series_uri", sa.String(512), nullable=True),
        sa.Column("series_summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(255), nullable=True),
        sa.Column("confirmed_activity_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_activity_id"],
            ["activities.id"],
            name="fk_imports_confirmed_activity_id_activities",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["raw_artifact_id"],
            ["raw_artifacts.id"],
            name="fk_imports_raw_artifact_id_raw_artifacts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_imports_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_imports"),
        sa.UniqueConstraint("raw_artifact_id", name="uq_imports_raw_artifact_id"),
    )
    op.create_table(
        "activity_splits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("split_index", sa.Integer(), nullable=False),
        sa.Column("distance_m", sa.Integer(), nullable=False),
        sa.Column("elapsed_time_sec", sa.Integer(), nullable=False),
        sa.Column("moving_time_sec", sa.Integer(), nullable=True),
        sa.Column("avg_pace_sec_per_km", sa.Integer(), nullable=False),
        sa.CheckConstraint("distance_m > 0", name="ck_activity_splits_distance_positive"),
        sa.CheckConstraint("elapsed_time_sec > 0", name="ck_activity_splits_elapsed_positive"),
        sa.CheckConstraint("split_index > 0", name="ck_activity_splits_index_positive"),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["activities.id"],
            name="fk_activity_splits_activity_id_activities",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_activity_splits"),
        sa.UniqueConstraint("activity_id", "split_index", name="uq_activity_splits_activity_index"),
    )
    op.create_index("ix_activity_splits_activity_id", "activity_splits", ["activity_id"])
    op.create_table(
        "activity_series",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("series_kind", sa.String(32), nullable=False),
        sa.Column("storage_uri", sa.String(512), nullable=False),
        sa.Column("content_encoding", sa.String(32), nullable=False),
        sa.Column("content_type", sa.String(127), nullable=False),
        sa.Column("point_count", sa.Integer(), nullable=False),
        sa.Column("summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("point_count > 0", name="ck_activity_series_point_count_positive"),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["activities.id"],
            name="fk_activity_series_activity_id_activities",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_activity_series"),
        sa.UniqueConstraint("activity_id", "series_kind", name="uq_activity_series_activity_kind"),
        sa.UniqueConstraint("storage_uri", name="uq_activity_series_storage_uri"),
    )
    op.create_index("ix_activity_series_activity_id", "activity_series", ["activity_id"])


def downgrade() -> None:
    op.drop_index("ix_activity_series_activity_id", table_name="activity_series")
    op.drop_table("activity_series")
    op.drop_index("ix_activity_splits_activity_id", table_name="activity_splits")
    op.drop_table("activity_splits")
    op.drop_table("imports")
    op.drop_table("raw_artifacts")
