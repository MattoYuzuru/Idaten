import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.activities.models import SourceType
from app.db.base import Base, TimestampMixin


class ImportStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PREVIEW = "PREVIEW"
    CONFIRMED = "CONFIRMED"
    DUPLICATE = "DUPLICATE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RawArtifact(Base):
    __tablename__ = "raw_artifacts"
    __table_args__ = (UniqueConstraint("user_id", "sha256", name="uq_raw_artifacts_user_sha256"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    storage_uri: Mapped[str] = mapped_column(String(512), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    original_filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(127))
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ActivityImport(TimestampMixin, Base):
    __tablename__ = "imports"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    raw_artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_artifacts.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[ImportStatus] = mapped_column(
        Enum(ImportStatus, native_enum=False, create_constraint=True, length=16)
    )
    source_type: Mapped[SourceType | None] = mapped_column(
        Enum(SourceType, native_enum=False, create_constraint=True, length=32)
    )
    normalized_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    draft_series_uri: Mapped[str | None] = mapped_column(String(512))
    series_summary_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(255))
    confirmed_activity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("activities.id", ondelete="SET NULL")
    )


class ActivitySplit(Base):
    __tablename__ = "activity_splits"
    __table_args__ = (
        CheckConstraint("split_index > 0", name="index_positive"),
        CheckConstraint("distance_m > 0", name="distance_positive"),
        CheckConstraint("elapsed_time_sec > 0", name="elapsed_positive"),
        UniqueConstraint("activity_id", "split_index", name="uq_activity_splits_activity_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    activity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE"), index=True
    )
    split_index: Mapped[int] = mapped_column(Integer)
    distance_m: Mapped[int] = mapped_column(Integer)
    elapsed_time_sec: Mapped[int] = mapped_column(Integer)
    moving_time_sec: Mapped[int | None] = mapped_column(Integer)
    avg_pace_sec_per_km: Mapped[int] = mapped_column(Integer)


class ActivitySeries(Base):
    __tablename__ = "activity_series"
    __table_args__ = (
        CheckConstraint("point_count > 0", name="point_count_positive"),
        UniqueConstraint("activity_id", "series_kind", name="uq_activity_series_activity_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    activity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE"), index=True
    )
    series_kind: Mapped[str] = mapped_column(String(32))
    storage_uri: Mapped[str] = mapped_column(String(512), unique=True)
    content_encoding: Mapped[str] = mapped_column(String(32))
    content_type: Mapped[str] = mapped_column(String(127))
    point_count: Mapped[int] = mapped_column(Integer)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
