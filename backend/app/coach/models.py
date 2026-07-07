import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class TrainingGoal(StrEnum):
    FIRST_10K = "FIRST_10K"
    HALF = "HALF"
    MARATHON = "MARATHON"
    CUSTOM = "CUSTOM"


class PlanStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class TrainingPlan(TimestampMixin, Base):
    __table_args__ = (
        UniqueConstraint("user_id", "starts_on", name="uq_training_plans_user_start"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    goal: Mapped[TrainingGoal] = mapped_column(
        Enum(TrainingGoal, native_enum=False, create_constraint=True, length=16)
    )
    custom_goal: Mapped[str | None] = mapped_column(String(255))
    starts_on: Mapped[date] = mapped_column(Date)
    weeks: Mapped[int] = mapped_column(Integer)
    baseline_weekly_distance_m: Mapped[int] = mapped_column(Integer)
    calculator_version: Mapped[str] = mapped_column(String(32))
    rule_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[PlanStatus] = mapped_column(
        Enum(PlanStatus, native_enum=False, create_constraint=True, length=16),
        default=PlanStatus.DRAFT,
    )


class PlannedWorkout(Base):
    __table_args__ = (
        UniqueConstraint("plan_id", "week_index", name="uq_planned_workouts_plan_week"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("training_plans.id", ondelete="CASCADE"), index=True
    )
    week_index: Mapped[int] = mapped_column(Integer)
    scheduled_for: Mapped[date] = mapped_column(Date)
    workout_type: Mapped[str] = mapped_column(String(24))
    distance_m: Mapped[int] = mapped_column(Integer)
    duration_sec: Mapped[int] = mapped_column(Integer)
    pace_min_sec_per_km: Mapped[int | None] = mapped_column(Integer)
    pace_max_sec_per_km: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    risk_flags: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
