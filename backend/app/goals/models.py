import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, ForeignKey, Index, Integer, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.goals.domain import RunningGoalStatus, RunningGoalType


class RunningGoal(TimestampMixin, Base):
    __table_args__ = (
        CheckConstraint(
            "((type IN ('IMPROVE_HALF', 'IMPROVE_MARATHON') "
            "AND target_duration_sec IS NOT NULL AND target_duration_sec > 0) OR "
            "(type NOT IN ('IMPROVE_HALF', 'IMPROVE_MARATHON') "
            "AND target_duration_sec IS NULL))",
            name="target_duration_matches_type",
        ),
        CheckConstraint(
            "((status = 'COMPLETED' AND completed_at IS NOT NULL) OR "
            "(status IN ('ACTIVE', 'CANCELLED') AND completed_at IS NULL))",
            name="completed_at_matches_status",
        ),
        Index(
            "uq_running_goals_active_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[RunningGoalType] = mapped_column(
        Enum(RunningGoalType, native_enum=False, create_constraint=True, length=24)
    )
    target_date: Mapped[date | None] = mapped_column(Date)
    target_duration_sec: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[RunningGoalStatus] = mapped_column(
        Enum(RunningGoalStatus, native_enum=False, create_constraint=True, length=16),
        default=RunningGoalStatus.ACTIVE,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
