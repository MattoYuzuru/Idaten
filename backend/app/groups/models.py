import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
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


class MonthlyOutboxStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class GroupGoal(Base):
    __tablename__ = "group_goals"
    __table_args__ = (
        UniqueConstraint("group_id", "period_start", name="uq_group_goals_group_period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("running_groups.id", ondelete="CASCADE"), index=True
    )
    period_start: Mapped[date] = mapped_column(Date)
    target_distance_m: Mapped[int] = mapped_column(Integer)


class GroupMonthlyReport(Base):
    __tablename__ = "group_monthly_reports"
    __table_args__ = (
        UniqueConstraint(
            "group_id", "period_start", "report_type", name="uq_group_monthly_report_period"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("running_groups.id", ondelete="CASCADE"), index=True
    )
    period_start: Mapped[date] = mapped_column(Date)
    report_type: Mapped[str] = mapped_column(String(16), default="MONTHLY")
    facts_json: Mapped[dict[str, object]] = mapped_column(JSON)
    message_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GroupReportOutbox(Base):
    __tablename__ = "group_report_outbox"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("group_monthly_reports.id", ondelete="CASCADE"), unique=True
    )
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger)
    message_text: Mapped[str] = mapped_column(Text)
    status: Mapped[MonthlyOutboxStatus] = mapped_column(
        Enum(MonthlyOutboxStatus, native_enum=False, create_constraint=True, length=16),
        default=MonthlyOutboxStatus.PENDING,
        index=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
