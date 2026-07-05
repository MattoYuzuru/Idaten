import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SourceType(StrEnum):
    MANUAL = "MANUAL"
    HEALTH_CONNECT = "HEALTH_CONNECT"
    STRAVA = "STRAVA"
    GPX = "GPX"
    FIT = "FIT"
    TCX = "TCX"
    CSV = "CSV"
    SCREENSHOT = "SCREENSHOT"
    SAMSUNG_EXPORT = "SAMSUNG_EXPORT"


class SourceStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    ERROR = "ERROR"


class ActivityType(StrEnum):
    RUN = "RUN"
    WALK = "WALK"
    BIKE = "BIKE"
    OTHER = "OTHER"


class ActivityVisibility(StrEnum):
    PRIVATE = "PRIVATE"
    GROUP_SUMMARY = "GROUP_SUMMARY"
    GROUP_DETAILED = "GROUP_DETAILED"
    PUBLIC = "PUBLIC"


class ActivitySource(TimestampMixin, Base):
    __table_args__ = (
        UniqueConstraint("user_id", "source_type", name="uq_activity_sources_user_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, native_enum=False, create_constraint=True, length=32)
    )
    status: Mapped[SourceStatus] = mapped_column(
        Enum(SourceStatus, native_enum=False, create_constraint=True, length=16),
        default=SourceStatus.ACTIVE,
    )
    external_account_id: Mapped[str | None] = mapped_column(String(255))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Activity(TimestampMixin, Base):
    __tablename__ = "activities"
    __table_args__ = (
        CheckConstraint("distance_m > 0", name="distance_positive"),
        CheckConstraint("elapsed_time_sec > 0", name="elapsed_positive"),
        Index(
            "uq_activities_source_external_id",
            "source_id",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
            sqlite_where=text("external_id IS NOT NULL"),
        ),
        Index("ix_activities_user_started_at", "user_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("activity_sources.id", ondelete="RESTRICT")
    )
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, native_enum=False, create_constraint=True, length=32)
    )
    external_id: Mapped[str | None] = mapped_column(String(255))
    activity_type: Mapped[ActivityType] = mapped_column(
        Enum(ActivityType, native_enum=False, create_constraint=True, length=16)
    )
    title: Mapped[str | None] = mapped_column(String(255))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64))
    distance_m: Mapped[int] = mapped_column(Integer)
    elapsed_time_sec: Mapped[int] = mapped_column(Integer)
    moving_time_sec: Mapped[int | None] = mapped_column(Integer)
    avg_pace_sec_per_km: Mapped[int] = mapped_column(Integer)
    avg_speed_mps: Mapped[float] = mapped_column(Float)
    avg_hr: Mapped[int | None] = mapped_column(Integer)
    max_hr: Mapped[int | None] = mapped_column(Integer)
    visibility: Mapped[ActivityVisibility] = mapped_column(
        Enum(ActivityVisibility, native_enum=False, create_constraint=True, length=24),
        default=ActivityVisibility.PRIVATE,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReportType(StrEnum):
    AFTER_RUN = "AFTER_RUN"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    PLAN = "PLAN"
    NEXT_WORKOUT = "NEXT_WORKOUT"


class CoachReport(Base):
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    activity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("activities.id", ondelete="SET NULL"), unique=True
    )
    report_type: Mapped[ReportType] = mapped_column(
        Enum(ReportType, native_enum=False, create_constraint=True, length=24)
    )
    facts_json: Mapped[dict[str, Any]] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    rule_result_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    message_private: Mapped[str] = mapped_column(Text)
    message_group: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
