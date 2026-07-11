"""Add consent-gated assisted activity input and extraction audit metadata."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260711_0007"
down_revision: str | None = "20260708_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_VALUES = (
    "MANUAL",
    "HEALTH_CONNECT",
    "STRAVA",
    "GPX",
    "FIT",
    "TCX",
    "CSV",
    "TEXT",
    "SCREENSHOT",
    "SAMSUNG_EXPORT",
)
OLD_SOURCE_VALUES = tuple(value for value in SOURCE_VALUES if value != "TEXT")


def _replace_source_constraints(values: tuple[str, ...]) -> None:
    allowed = ", ".join(f"'{value}'" for value in values)
    for table in ("activity_sources", "activities", "imports"):
        constraint_name = op.f(f"ck_{table}_sourcetype")
        op.drop_constraint(constraint_name, table, type_="check")
        op.create_check_constraint(
            constraint_name,
            table,
            f"source_type IN ({allowed})",
        )


def upgrade() -> None:
    _replace_source_constraints(SOURCE_VALUES)
    op.add_column(
        "activities",
        sa.Column("start_time_known", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column("activities", "start_time_known", server_default=None)
    op.add_column("users", sa.Column("assisted_input_consent_version", sa.String(32)))
    op.add_column("users", sa.Column("assisted_input_consented_at", sa.DateTime(timezone=True)))

    input_method = sa.Enum(
        "STEPS",
        "TEXT",
        "SCREENSHOT",
        name="draftinputmethod",
        native_enum=False,
        create_constraint=True,
        length=16,
    )
    source_type = sa.Enum(
        *SOURCE_VALUES,
        name="sourcetype",
        native_enum=False,
        create_constraint=True,
        length=32,
    )
    op.add_column(
        "manual_activity_drafts",
        sa.Column("input_method", input_method, nullable=False, server_default="STEPS"),
    )
    op.add_column(
        "manual_activity_drafts",
        sa.Column("source_type", source_type, nullable=False, server_default="MANUAL"),
    )
    op.add_column(
        "manual_activity_drafts",
        sa.Column("date_confirmed", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "manual_activity_drafts",
        sa.Column("start_time_known", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    for column in ("input_method", "source_type", "date_confirmed", "start_time_known"):
        op.alter_column("manual_activity_drafts", column, server_default=None)
    op.add_column("manual_activity_drafts", sa.Column("input_sha256", sa.String(64)))
    op.add_column("manual_activity_drafts", sa.Column("provider", sa.String(32)))
    op.add_column("manual_activity_drafts", sa.Column("provider_model", sa.String(128)))
    op.add_column("manual_activity_drafts", sa.Column("provider_request_id", sa.String(128)))

    access_status = sa.Enum(
        "PENDING",
        "ALLOWED",
        "REVOKED",
        name="assistedaccessstatus",
        native_enum=False,
        create_constraint=True,
        length=16,
    )
    op.create_table(
        "assisted_access",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", access_status, nullable=False),
        sa.Column("notification_sent_at", sa.DateTime(timezone=True)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decided_by_telegram_user_id", sa.BigInteger()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    attempt_status = sa.Enum(
        "PROCESSING",
        "SUCCEEDED",
        "FAILED",
        name="extractionattemptstatus",
        native_enum=False,
        create_constraint=True,
        length=16,
    )
    op.create_table(
        "extraction_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("input_method", input_method, nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_model", sa.String(128), nullable=False),
        sa.Column("provider_request_id", sa.String(128)),
        sa.Column("status", attempt_status, nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["draft_id"], ["manual_activity_drafts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_extraction_attempts_user_created", "extraction_attempts", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_extraction_attempts_draft_hash_status",
        "extraction_attempts",
        ["draft_id", "input_sha256", "status"],
    )
    op.create_index("ix_extraction_attempts_created_at", "extraction_attempts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_extraction_attempts_created_at", table_name="extraction_attempts")
    op.drop_index("ix_extraction_attempts_draft_hash_status", table_name="extraction_attempts")
    op.drop_index("ix_extraction_attempts_user_created", table_name="extraction_attempts")
    op.drop_table("extraction_attempts")
    op.drop_table("assisted_access")
    for column in (
        "provider_request_id",
        "provider_model",
        "provider",
        "input_sha256",
        "start_time_known",
        "date_confirmed",
        "source_type",
        "input_method",
    ):
        op.drop_column("manual_activity_drafts", column)
    op.drop_column("users", "assisted_input_consented_at")
    op.drop_column("users", "assisted_input_consent_version")
    op.drop_column("activities", "start_time_known")
    op.execute(
        """
        UPDATE activities AS activity
        SET source_id = manual_source.id
        FROM activity_sources AS text_source
        JOIN activity_sources AS manual_source
          ON manual_source.user_id = text_source.user_id
         AND manual_source.source_type = 'MANUAL'
        WHERE activity.source_id = text_source.id
          AND text_source.source_type = 'TEXT'
        """
    )
    op.execute(
        """
        DELETE FROM activity_sources AS text_source
        USING activity_sources AS manual_source
        WHERE text_source.source_type = 'TEXT'
          AND manual_source.source_type = 'MANUAL'
          AND manual_source.user_id = text_source.user_id
        """
    )
    op.execute("UPDATE activity_sources SET source_type = 'MANUAL' WHERE source_type = 'TEXT'")
    op.execute("UPDATE activities SET source_type = 'MANUAL' WHERE source_type = 'TEXT'")
    op.execute("UPDATE imports SET source_type = 'MANUAL' WHERE source_type = 'TEXT'")
    _replace_source_constraints(OLD_SOURCE_VALUES)
