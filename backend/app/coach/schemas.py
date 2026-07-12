import uuid
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from app.coach.domain import CoachFacts, WorkoutRecommendation
from app.coach.models import TrainingGoal
from app.goals.schemas import GoalAchievement, RunningGoalDto
from app.readiness.schemas import ReadinessDraft


class CoachError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class WeekResponse:
    facts: CoachFacts
    message: str


@dataclass(frozen=True, slots=True)
class PlanWorkout:
    week_index: int
    scheduled_for: date
    recommendation: WorkoutRecommendation


@dataclass(frozen=True, slots=True)
class PlanResponse:
    plan_id: uuid.UUID
    goal: TrainingGoal
    baseline_weekly_distance_m: int
    workouts: tuple[PlanWorkout, ...]
    message: str


class NextFlowState(StrEnum):
    NEED_GOAL = "NEED_GOAL"
    NEED_CHECK_IN_METHOD = "NEED_CHECK_IN_METHOD"
    EDIT_CHECK_IN = "EDIT_CHECK_IN"
    SHOW_PROVISIONAL = "SHOW_PROVISIONAL"
    NEED_PRE_RUN_CHECK_IN = "NEED_PRE_RUN_CHECK_IN"
    SHOW_CONFIRMED = "SHOW_CONFIRMED"
    GOAL_ACHIEVEMENT_CONFIRMATION = "GOAL_ACHIEVEMENT_CONFIRMATION"


@dataclass(frozen=True, slots=True)
class RecommendationDto:
    recommendation_id: uuid.UUID
    status: str
    report_id: uuid.UUID
    check_in_id: uuid.UUID
    recommended_for: date
    not_before: datetime
    valid_until: datetime
    message: str
    inputs_fingerprint: str


@dataclass(frozen=True, slots=True)
class NextFlowResult:
    state: NextFlowState
    goal: RunningGoalDto | None = None
    check_in: ReadinessDraft | None = None
    recommendation: RecommendationDto | None = None
    achievement: GoalAchievement | None = None
