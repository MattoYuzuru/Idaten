import uuid
from dataclasses import dataclass
from datetime import date

from app.coach.domain import CoachFacts, WorkoutRecommendation
from app.coach.models import TrainingGoal


class CoachError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CoachResponse:
    report_id: uuid.UUID
    facts: CoachFacts
    recommendation: WorkoutRecommendation
    message: str
    provider: str


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
