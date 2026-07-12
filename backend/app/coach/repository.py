import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.activities.models import CoachReport
from app.coach.models import (
    NextRunRecommendation,
    PlannedWorkout,
    RecommendationStatus,
    TrainingPlan,
)


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

    async def current_recommendation(
        self, user_id: uuid.UUID, *, for_update: bool = False
    ) -> NextRunRecommendation | None:
        statement = select(NextRunRecommendation).where(
            NextRunRecommendation.user_id == user_id,
            NextRunRecommendation.status.in_(
                (RecommendationStatus.PROVISIONAL, RecommendationStatus.CONFIRMED)
            ),
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def recommendation_by_check_in(
        self, check_in_id: uuid.UUID
    ) -> NextRunRecommendation | None:
        result = await self.session.execute(
            select(NextRunRecommendation).where(NextRunRecommendation.check_in_id == check_in_id)
        )
        return result.scalar_one_or_none()

    async def recommendation_by_idempotency(
        self, user_id: uuid.UUID, key: str
    ) -> NextRunRecommendation | None:
        result = await self.session.execute(
            select(NextRunRecommendation).where(
                NextRunRecommendation.user_id == user_id,
                NextRunRecommendation.idempotency_key == key,
            )
        )
        return result.scalar_one_or_none()

    async def recommendation(self, recommendation_id: uuid.UUID) -> NextRunRecommendation | None:
        return await self.session.get(NextRunRecommendation, recommendation_id)

    def add_recommendation(self, recommendation: NextRunRecommendation) -> None:
        self.session.add(recommendation)
