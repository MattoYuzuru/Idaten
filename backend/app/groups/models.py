import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class GroupRole(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class ShareLevel(StrEnum):
    NONE = "NONE"
    SUMMARY = "SUMMARY"
    DETAILED = "DETAILED"


class PrivacySettings(TimestampMixin, Base):
    __tablename__ = "privacy_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    group_sharing_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class RunningGroup(TimestampMixin, Base):
    __tablename__ = "running_groups"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(64))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )


class GroupMember(TimestampMixin, Base):
    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_members_group_user"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("running_groups.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[GroupRole] = mapped_column(
        Enum(GroupRole, native_enum=False, create_constraint=True, length=16)
    )
    share_level: Mapped[ShareLevel] = mapped_column(
        Enum(ShareLevel, native_enum=False, create_constraint=True, length=16),
        default=ShareLevel.NONE,
    )
    auto_share: Mapped[bool] = mapped_column(Boolean, default=False)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActivityShareGrant(Base):
    __tablename__ = "activity_share_grants"
    __table_args__ = (
        UniqueConstraint("group_id", "activity_id", name="uq_activity_share_grants_group_activity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("running_groups.id", ondelete="CASCADE"), index=True
    )
    activity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    share_level: Mapped[ShareLevel] = mapped_column(
        Enum(ShareLevel, native_enum=False, create_constraint=True, length=16)
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GroupPublication(Base):
    __tablename__ = "group_publications"
    __table_args__ = (
        UniqueConstraint("group_id", "activity_id", name="uq_group_publications_group_activity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("running_groups.id", ondelete="CASCADE"), index=True
    )
    activity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    share_level: Mapped[ShareLevel] = mapped_column(
        Enum(ShareLevel, native_enum=False, create_constraint=True, length=16)
    )
    message_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
