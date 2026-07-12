"""Generalize external AI access, consent and task audit."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260712_0011"
down_revision: str | None = "20260712_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table("assisted_access", "external_ai_access")
    op.execute(
        "ALTER TABLE external_ai_access RENAME CONSTRAINT "
        "pk_assisted_access TO pk_external_ai_access"
    )
    op.execute(
        "ALTER TABLE external_ai_access RENAME CONSTRAINT "
        "fk_assisted_access_user_id_users TO fk_external_ai_access_user_id_users"
    )
    op.drop_constraint(
        op.f("ck_assisted_access_assistedaccessstatus"),
        "external_ai_access",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_external_ai_access_externalaiaccessstatus"),
        "external_ai_access",
        "status IN ('PENDING', 'ALLOWED', 'REVOKED')",
    )
    for name in (
        "ix_extraction_attempts_created_at",
        "ix_extraction_attempts_draft_hash_status",
        "ix_extraction_attempts_user_created",
    ):
        op.drop_index(name, table_name="extraction_attempts")
    op.rename_table("extraction_attempts", "ai_attempts")
    for old, new in (
        ("pk_extraction_attempts", "pk_ai_attempts"),
        (
            "fk_extraction_attempts_draft_id_manual_activity_drafts",
            "fk_ai_attempts_draft_id_manual_activity_drafts",
        ),
        ("fk_extraction_attempts_user_id_users", "fk_ai_attempts_user_id_users"),
        ("ck_extraction_attempts_draftinputmethod", "ck_ai_attempts_draftinputmethod"),
    ):
        op.execute(f"ALTER TABLE ai_attempts RENAME CONSTRAINT {old} TO {new}")
    op.drop_constraint(
        op.f("ck_extraction_attempts_extractionattemptstatus"),
        "ai_attempts",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_ai_attempts_aiattemptstatus"),
        "ai_attempts",
        "status IN ('PROCESSING', 'SUCCEEDED', 'FAILED')",
    )
    task = sa.Enum(
        "ACTIVITY_EXTRACTION",
        "READINESS_EXTRACTION",
        "VOICE_TRANSCRIPTION",
        name="aitask",
        native_enum=False,
        create_constraint=True,
        length=32,
    )
    op.add_column(
        "ai_attempts",
        sa.Column("task", task, nullable=False, server_default="ACTIVITY_EXTRACTION"),
    )
    op.alter_column("ai_attempts", "task", server_default=None)
    op.alter_column("ai_attempts", "draft_id", existing_type=sa.Uuid(), nullable=True)
    op.alter_column("ai_attempts", "input_method", existing_type=sa.String(16), nullable=True)
    op.create_index("ix_ai_attempts_user_created", "ai_attempts", ["user_id", "created_at"])
    op.create_index(
        "ix_ai_attempts_draft_hash_status",
        "ai_attempts",
        ["draft_id", "input_sha256", "status"],
    )
    op.create_index("ix_ai_attempts_created_at", "ai_attempts", ["created_at"])
    op.alter_column(
        "users",
        "assisted_input_consent_version",
        new_column_name="external_ai_consent_version",
        existing_type=sa.String(32),
    )
    op.alter_column(
        "users",
        "assisted_input_consented_at",
        new_column_name="external_ai_consented_at",
        existing_type=sa.DateTime(timezone=True),
    )
    op.drop_column("users", "external_processing_enabled")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "external_processing_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column("users", "external_processing_enabled", server_default=None)
    op.alter_column(
        "users",
        "external_ai_consented_at",
        new_column_name="assisted_input_consented_at",
        existing_type=sa.DateTime(timezone=True),
    )
    op.alter_column(
        "users",
        "external_ai_consent_version",
        new_column_name="assisted_input_consent_version",
        existing_type=sa.String(32),
    )
    op.drop_index("ix_ai_attempts_created_at", table_name="ai_attempts")
    op.drop_index("ix_ai_attempts_draft_hash_status", table_name="ai_attempts")
    op.drop_index("ix_ai_attempts_user_created", table_name="ai_attempts")
    op.execute("DELETE FROM ai_attempts WHERE task != 'ACTIVITY_EXTRACTION'")
    op.alter_column("ai_attempts", "input_method", existing_type=sa.String(16), nullable=False)
    op.alter_column("ai_attempts", "draft_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_column("ai_attempts", "task")
    op.drop_constraint(op.f("ck_ai_attempts_aiattemptstatus"), "ai_attempts", type_="check")
    op.create_check_constraint(
        op.f("ck_extraction_attempts_extractionattemptstatus"),
        "ai_attempts",
        "status IN ('PROCESSING', 'SUCCEEDED', 'FAILED')",
    )
    for old, new in (
        ("pk_ai_attempts", "pk_extraction_attempts"),
        (
            "fk_ai_attempts_draft_id_manual_activity_drafts",
            "fk_extraction_attempts_draft_id_manual_activity_drafts",
        ),
        ("fk_ai_attempts_user_id_users", "fk_extraction_attempts_user_id_users"),
        ("ck_ai_attempts_draftinputmethod", "ck_extraction_attempts_draftinputmethod"),
    ):
        op.execute(f"ALTER TABLE ai_attempts RENAME CONSTRAINT {old} TO {new}")
    op.rename_table("ai_attempts", "extraction_attempts")
    op.create_index(
        "ix_extraction_attempts_user_created",
        "extraction_attempts",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_extraction_attempts_draft_hash_status",
        "extraction_attempts",
        ["draft_id", "input_sha256", "status"],
    )
    op.create_index("ix_extraction_attempts_created_at", "extraction_attempts", ["created_at"])
    op.drop_constraint(
        op.f("ck_external_ai_access_externalaiaccessstatus"),
        "external_ai_access",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_assisted_access_assistedaccessstatus"),
        "external_ai_access",
        "status IN ('PENDING', 'ALLOWED', 'REVOKED')",
    )
    op.execute(
        "ALTER TABLE external_ai_access RENAME CONSTRAINT "
        "fk_external_ai_access_user_id_users TO fk_assisted_access_user_id_users"
    )
    op.execute(
        "ALTER TABLE external_ai_access RENAME CONSTRAINT "
        "pk_external_ai_access TO pk_assisted_access"
    )
    op.rename_table("external_ai_access", "assisted_access")
