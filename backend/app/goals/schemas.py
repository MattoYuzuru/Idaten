import uuid
from dataclasses import dataclass
from datetime import date, datetime

from app.goals.models import RunningGoalStatus, RunningGoalType


class GoalError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RunningGoalDto:
    goal_id: uuid.UUID
    type: RunningGoalType
    status: RunningGoalStatus
    target_date: date | None
    target_duration_sec: int | None
    started_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class GoalAchievement:
    goal: RunningGoalDto
    activity_id: uuid.UUID
    achieved_at: datetime
