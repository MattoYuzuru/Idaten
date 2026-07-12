import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.readiness.domain import CheckInInputSource, CheckInPhase, CheckInStatus


class ReadinessCheckIn(TimestampMixin, Base):
    __table_args__ = (
        CheckConstraint(
            "overall_readiness IS NULL OR overall_readiness BETWEEN 1 AND 5",
            name="overall_readiness_range",
        ),
        CheckConstraint(
            "general_fatigue IS NULL OR general_fatigue BETWEEN 0 AND 10",
            name="general_fatigue_range",
        ),
        CheckConstraint(
            "muscle_soreness IS NULL OR muscle_soreness BETWEEN 0 AND 10",
            name="muscle_soreness_range",
        ),
        CheckConstraint(
            "motivation IS NULL OR motivation BETWEEN 1 AND 5", name="motivation_range"
        ),
        CheckConstraint(
            "sleep_quality IS NULL OR sleep_quality BETWEEN 1 AND 5", name="sleep_quality_range"
        ),
        CheckConstraint(
            "sleep_duration_sec IS NULL OR sleep_duration_sec BETWEEN 1 AND 86400",
            name="sleep_duration_range",
        ),
        CheckConstraint(
            "external_load IS NULL OR external_load BETWEEN 0 AND 10", name="external_load_range"
        ),
        CheckConstraint(
            "pain_severity IS NULL OR pain_severity BETWEEN 0 AND 10", name="pain_severity_range"
        ),
        CheckConstraint(
            "((pain_present IS NULL) OR "
            "(pain_present = false AND pain_severity IS NULL AND pain_location IS NULL "
            "AND pain_affects_movement IS NULL AND pain_is_new IS NULL "
            "AND pain_is_worsening IS NULL) OR "
            "(pain_present = true AND (status != 'CONFIRMED' OR "
            "(pain_severity IS NOT NULL AND pain_location IS NOT NULL "
            "AND pain_affects_movement IS NOT NULL AND pain_is_new IS NOT NULL "
            "AND pain_is_worsening IS NOT NULL))))",
            name="pain_fields_consistent",
        ),
        CheckConstraint(
            "available_time_sec IS NULL OR available_time_sec BETWEEN 1 AND 86400",
            name="available_time_range",
        ),
        CheckConstraint(
            "session_rpe IS NULL OR session_rpe BETWEEN 1 AND 10", name="session_rpe_range"
        ),
        CheckConstraint(
            "phase = 'POST_RUN' OR session_rpe IS NULL", name="session_rpe_post_run_only"
        ),
        CheckConstraint(
            "source_confidence IS NULL OR source_confidence BETWEEN 0 AND 1",
            name="source_confidence_range",
        ),
        CheckConstraint(
            "status != 'CONFIRMED' OR (overall_readiness IS NOT NULL "
            "AND general_fatigue IS NOT NULL AND muscle_soreness IS NOT NULL "
            "AND external_load IS NOT NULL AND pain_present IS NOT NULL "
            "AND illness_symptoms IS NOT NULL)",
            name="confirmed_required_fields",
        ),
        Index(
            "uq_readiness_check_ins_active_user_phase",
            "user_id",
            "phase",
            unique=True,
            postgresql_where=text("status = 'DRAFT'"),
            sqlite_where=text("status = 'DRAFT'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    phase: Mapped[CheckInPhase] = mapped_column(
        Enum(CheckInPhase, native_enum=False, create_constraint=True, length=16)
    )
    status: Mapped[CheckInStatus] = mapped_column(
        Enum(CheckInStatus, native_enum=False, create_constraint=True, length=16)
    )
    source: Mapped[CheckInInputSource] = mapped_column(
        Enum(CheckInInputSource, native_enum=False, create_constraint=True, length=24)
    )
    source_confidence: Mapped[float | None] = mapped_column(Float)
    overall_readiness: Mapped[int | None] = mapped_column(Integer)
    general_fatigue: Mapped[int | None] = mapped_column(Integer)
    muscle_soreness: Mapped[int | None] = mapped_column(Integer)
    motivation: Mapped[int | None] = mapped_column(Integer)
    sleep_quality: Mapped[int | None] = mapped_column(Integer)
    sleep_duration_sec: Mapped[int | None] = mapped_column(Integer)
    sleep_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sleep_summary_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    external_load: Mapped[int | None] = mapped_column(Integer)
    pain_present: Mapped[bool | None] = mapped_column(Boolean)
    pain_severity: Mapped[int | None] = mapped_column(Integer)
    pain_location: Mapped[str | None] = mapped_column(String(120))
    pain_affects_movement: Mapped[bool | None] = mapped_column(Boolean)
    pain_is_new: Mapped[bool | None] = mapped_column(Boolean)
    pain_is_worsening: Mapped[bool | None] = mapped_column(Boolean)
    illness_symptoms: Mapped[bool | None] = mapped_column(Boolean)
    available_time_sec: Mapped[int | None] = mapped_column(Integer)
    session_rpe: Mapped[int | None] = mapped_column(Integer)
    linked_activity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("activities.id", ondelete="SET NULL")
    )
    pending_field: Mapped[str | None] = mapped_column(String(32))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
