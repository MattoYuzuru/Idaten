import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
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

from app.activities.domain import SourceType as SourceType
from app.db.base import Base, TimestampMixin


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
        CheckConstraint(
            "avg_cadence_spm IS NULL OR (avg_cadence_spm >= 30 AND avg_cadence_spm <= 300)",
            name="avg_cadence_range",
        ),
        CheckConstraint(
            "elevation_gain_m IS NULL OR (elevation_gain_m >= 0 AND elevation_gain_m <= 20000)",
            name="elevation_gain_range",
        ),
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
    start_time_known: Mapped[bool] = mapped_column(Boolean, default=True)
    timezone: Mapped[str] = mapped_column(String(64))
    distance_m: Mapped[int] = mapped_column(Integer)
    elapsed_time_sec: Mapped[int] = mapped_column(Integer)
    moving_time_sec: Mapped[int | None] = mapped_column(Integer)
    avg_pace_sec_per_km: Mapped[int] = mapped_column(Integer)
    avg_speed_mps: Mapped[float] = mapped_column(Float)
    avg_hr: Mapped[int | None] = mapped_column(Integer)
    max_hr: Mapped[int | None] = mapped_column(Integer)
    avg_cadence_spm: Mapped[int | None] = mapped_column(Integer)
    elevation_gain_m: Mapped[int | None] = mapped_column(Integer)
    visibility: Mapped[ActivityVisibility] = mapped_column(
        Enum(ActivityVisibility, native_enum=False, create_constraint=True, length=24),
        default=ActivityVisibility.PRIVATE,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ManualDraftStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SAVED = "SAVED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class DraftInputMethod(StrEnum):
    STEPS = "STEPS"
    TEXT = "TEXT"
    SCREENSHOT = "SCREENSHOT"


class ManualActivityDraft(TimestampMixin, Base):
    __tablename__ = "manual_activity_drafts"
    __table_args__ = (
        CheckConstraint("distance_m IS NULL OR distance_m > 0", name="distance_positive"),
        CheckConstraint(
            "elapsed_time_sec IS NULL OR elapsed_time_sec > 0", name="elapsed_positive"
        ),
        CheckConstraint(
            "moving_time_sec IS NULL OR elapsed_time_sec IS NULL OR "
            "(moving_time_sec > 0 AND moving_time_sec <= elapsed_time_sec)",
            name="moving_not_greater_than_elapsed",
        ),
        CheckConstraint(
            "avg_hr IS NULL OR (avg_hr >= 20 AND avg_hr <= 260)",
            name="avg_hr_range",
        ),
        CheckConstraint(
            "max_hr IS NULL OR (max_hr >= 20 AND max_hr <= 260)",
            name="max_hr_range",
        ),
        CheckConstraint(
            "avg_hr IS NULL OR max_hr IS NULL OR avg_hr <= max_hr",
            name="avg_hr_not_greater_than_max",
        ),
        CheckConstraint(
            "avg_cadence_spm IS NULL OR (avg_cadence_spm >= 30 AND avg_cadence_spm <= 300)",
            name="avg_cadence_range",
        ),
        CheckConstraint(
            "elevation_gain_m IS NULL OR (elevation_gain_m >= 0 AND elevation_gain_m <= 20000)",
            name="elevation_gain_range",
        ),
        Index(
            "uq_manual_activity_drafts_active_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[ManualDraftStatus] = mapped_column(
        Enum(ManualDraftStatus, native_enum=False, create_constraint=True, length=16),
        default=ManualDraftStatus.ACTIVE,
    )
    input_method: Mapped[DraftInputMethod] = mapped_column(
        Enum(DraftInputMethod, native_enum=False, create_constraint=True, length=16),
        default=DraftInputMethod.STEPS,
    )
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, native_enum=False, create_constraint=True, length=32),
        default=SourceType.MANUAL,
    )
    distance_m: Mapped[int | None] = mapped_column(Integer)
    elapsed_time_sec: Mapped[int | None] = mapped_column(Integer)
    moving_time_sec: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    date_confirmed: Mapped[bool] = mapped_column(Boolean, default=True)
    start_time_known: Mapped[bool] = mapped_column(Boolean, default=True)
    timezone: Mapped[str] = mapped_column(String(64))
    avg_hr: Mapped[int | None] = mapped_column(Integer)
    max_hr: Mapped[int | None] = mapped_column(Integer)
    avg_cadence_spm: Mapped[int | None] = mapped_column(Integer)
    elevation_gain_m: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(String(255))
    pending_field: Mapped[str | None] = mapped_column(String(32))
    telegram_message_id: Mapped[int | None] = mapped_column(Integer)
    input_sha256: Mapped[str | None] = mapped_column(String(64))
    provider: Mapped[str | None] = mapped_column(String(32))
    provider_model: Mapped[str | None] = mapped_column(String(128))
    provider_request_id: Mapped[str | None] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    activity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("activities.id", ondelete="SET NULL")
    )


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
    provider: Mapped[str] = mapped_column(String(32), default="NONE")
    provider_model: Mapped[str | None] = mapped_column(String(128))
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
