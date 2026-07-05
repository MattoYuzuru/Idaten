"""Add MVP 0.2 groups, privacy, grants, and publications."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260706_0002"
down_revision: str | None = "20260705_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    group_role = sa.Enum(
        "OWNER",
        "ADMIN",
        "MEMBER",
        name="grouprole",
        native_enum=False,
        create_constraint=True,
        length=16,
    )
    share_level = sa.Enum(
        "NONE",
        "SUMMARY",
        "DETAILED",
        name="sharelevel",
        native_enum=False,
        create_constraint=True,
        length=16,
    )

    op.create_table(
        "privacy_settings",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("group_sharing_enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_privacy_settings_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_privacy_settings"),
    )
    op.create_table(
        "running_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_running_groups_created_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_running_groups"),
    )
    op.create_index(
        "ix_running_groups_telegram_chat_id",
        "running_groups",
        ["telegram_chat_id"],
        unique=True,
    )
    op.create_table(
        "group_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", group_role, nullable=False),
        sa.Column("share_level", share_level, nullable=False),
        sa.Column("auto_share", sa.Boolean(), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["running_groups.id"],
            name="fk_group_members_group_id_running_groups",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_group_members_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_group_members"),
        sa.UniqueConstraint("group_id", "user_id", name="uq_group_members_group_user"),
    )
    op.create_index("ix_group_members_group_id", "group_members", ["group_id"])
    op.create_index("ix_group_members_user_id", "group_members", ["user_id"])
    op.create_table(
        "activity_share_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("share_level", share_level, nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["activities.id"],
            name="fk_activity_share_grants_activity_id_activities",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["running_groups.id"],
            name="fk_activity_share_grants_group_id_running_groups",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_activity_share_grants_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_activity_share_grants"),
        sa.UniqueConstraint(
            "group_id", "activity_id", name="uq_activity_share_grants_group_activity"
        ),
    )
    op.create_index(
        "ix_activity_share_grants_activity_id", "activity_share_grants", ["activity_id"]
    )
    op.create_index("ix_activity_share_grants_group_id", "activity_share_grants", ["group_id"])
    op.create_table(
        "group_publications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("share_level", share_level, nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["activities.id"],
            name="fk_group_publications_activity_id_activities",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["running_groups.id"],
            name="fk_group_publications_group_id_running_groups",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_group_publications_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_group_publications"),
        sa.UniqueConstraint("group_id", "activity_id", name="uq_group_publications_group_activity"),
    )
    op.create_index("ix_group_publications_activity_id", "group_publications", ["activity_id"])
    op.create_index("ix_group_publications_group_id", "group_publications", ["group_id"])


def downgrade() -> None:
    op.drop_index("ix_group_publications_group_id", table_name="group_publications")
    op.drop_index("ix_group_publications_activity_id", table_name="group_publications")
    op.drop_table("group_publications")
    op.drop_index("ix_activity_share_grants_group_id", table_name="activity_share_grants")
    op.drop_index("ix_activity_share_grants_activity_id", table_name="activity_share_grants")
    op.drop_table("activity_share_grants")
    op.drop_index("ix_group_members_user_id", table_name="group_members")
    op.drop_index("ix_group_members_group_id", table_name="group_members")
    op.drop_table("group_members")
    op.drop_index("ix_running_groups_telegram_chat_id", table_name="running_groups")
    op.drop_table("running_groups")
    op.drop_table("privacy_settings")
