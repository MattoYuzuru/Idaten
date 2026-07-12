import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.goals.models import RunningGoal, RunningGoalStatus


class GoalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def active(self, user_id: uuid.UUID, *, for_update: bool = False) -> RunningGoal | None:
        statement = select(RunningGoal).where(
            RunningGoal.user_id == user_id,
            RunningGoal.status == RunningGoalStatus.ACTIVE,
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def by_id(self, goal_id: uuid.UUID, *, for_update: bool = False) -> RunningGoal | None:
        statement = select(RunningGoal).where(RunningGoal.id == goal_id)
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def history(self, user_id: uuid.UUID) -> tuple[RunningGoal, ...]:
        result = await self.session.scalars(
            select(RunningGoal)
            .where(RunningGoal.user_id == user_id)
            .order_by(RunningGoal.started_at, RunningGoal.id)
        )
        return tuple(result.all())

    def add(self, goal: RunningGoal) -> None:
        self.session.add(goal)
