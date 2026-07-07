import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.activities.models import CoachReport
from app.coach.models import PlannedWorkout, TrainingPlan


class CoachRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add_report(self, report: CoachReport) -> None:
        self.session.add(report)

    def add_plan(self, plan: TrainingPlan) -> None:
        self.session.add(plan)

    def add_workout(self, workout: PlannedWorkout) -> None:
        self.session.add(workout)

    async def plan_for_start(self, user_id: uuid.UUID, starts_on: date) -> TrainingPlan | None:
        result = await self.session.execute(
            select(TrainingPlan).where(
                TrainingPlan.user_id == user_id, TrainingPlan.starts_on == starts_on
            )
        )
        return result.scalar_one_or_none()

    async def report(self, report_id: uuid.UUID) -> CoachReport | None:
        return await self.session.get(CoachReport, report_id)
