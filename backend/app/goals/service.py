import uuid
from datetime import UTC, date, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.activities.repository import ActivityRepository
from app.activities.schemas import RunHistoryItem
from app.activities.standards import is_actual_distance, proves_finish
from app.goals.domain import (
    GOAL_DISTANCES,
    IMPROVEMENT_GOALS,
    RunningGoalStatus,
    RunningGoalType,
)
from app.goals.models import RunningGoal
from app.goals.repository import GoalRepository
from app.goals.schemas import GoalAchievement, GoalError, RunningGoalDto
from app.users.models import User
from app.users.repository import UserRepository


class GoalService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def active(self, telegram_user_id: int) -> RunningGoalDto | None:
        async with self.session_factory() as session:
            user = await self._require_user(session, telegram_user_id)
            goal = await GoalRepository(session).active(user.id)
            return None if goal is None else self._dto(goal)

    async def history(self, telegram_user_id: int) -> tuple[RunningGoalDto, ...]:
        async with self.session_factory() as session:
            user = await self._require_user(session, telegram_user_id)
            goals = await GoalRepository(session).history(user.id)
            return tuple(self._dto(goal) for goal in goals)

    async def select(
        self,
        telegram_user_id: int,
        goal_type: RunningGoalType,
        *,
        target_date: date | None = None,
        target_duration_sec: int | None = None,
        moment: datetime | None = None,
    ) -> RunningGoalDto:
        self._validate(goal_type, target_duration_sec)
        now = moment or datetime.now(UTC)
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            repository = GoalRepository(session)
            current = await repository.active(user.id, for_update=True)
            if current is not None:
                current.status = RunningGoalStatus.CANCELLED
            goal = RunningGoal(
                user_id=user.id,
                type=goal_type,
                target_date=target_date,
                target_duration_sec=target_duration_sec,
                status=RunningGoalStatus.ACTIVE,
                started_at=now,
            )
            repository.add(goal)
            await session.flush()
            return self._dto(goal)

    async def achievement(
        self, telegram_user_id: int, *, moment: datetime | None = None
    ) -> GoalAchievement | None:
        now = moment or datetime.now(UTC)
        async with self.session_factory() as session:
            user = await self._require_user(session, telegram_user_id)
            goal = await GoalRepository(session).active(user.id)
            if goal is None or goal.type == RunningGoalType.GENERAL_ENDURANCE:
                return None
            history = await ActivityRepository(session).run_history(user.id, started_before=now)
            achieved = self._achieving_run(goal, history)
            if achieved is None:
                return None
            return GoalAchievement(self._dto(goal), achieved.activity_id, achieved.started_at)

    async def complete(
        self, telegram_user_id: int, goal_id: uuid.UUID, *, moment: datetime | None = None
    ) -> RunningGoalDto:
        now = moment or datetime.now(UTC)
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            goal = await GoalRepository(session).by_id(goal_id, for_update=True)
            if goal is None or goal.user_id != user.id:
                raise GoalError("Цель не найдена.")
            if goal.status == RunningGoalStatus.COMPLETED:
                return self._dto(goal)
            if goal.status != RunningGoalStatus.ACTIVE:
                raise GoalError("Эта цель уже закрыта.")
            history = await ActivityRepository(session).run_history(user.id, started_before=now)
            if self._achieving_run(goal, history) is None:
                raise GoalError("В истории пока нет результата, подтверждающего эту цель.")
            goal.status = RunningGoalStatus.COMPLETED
            goal.completed_at = now
            return self._dto(goal)

    @staticmethod
    def _achieving_run(
        goal: RunningGoal, history: tuple[RunHistoryItem, ...]
    ) -> RunHistoryItem | None:
        target = GOAL_DISTANCES[goal.type]
        eligible = tuple(item for item in history if item.started_at >= goal.started_at)
        if goal.type in IMPROVEMENT_GOALS:
            assert goal.target_duration_sec is not None
            eligible = tuple(
                item
                for item in eligible
                if is_actual_distance(item.distance_m, target)
                and item.elapsed_time_sec <= goal.target_duration_sec
            )
        else:
            eligible = tuple(item for item in eligible if proves_finish(item.distance_m, target))
        return min(eligible, key=lambda item: (item.started_at, item.activity_id.hex), default=None)

    @staticmethod
    def _validate(goal_type: RunningGoalType, target_duration_sec: int | None) -> None:
        if goal_type in IMPROVEMENT_GOALS:
            if target_duration_sec is None or target_duration_sec <= 0:
                raise GoalError("Для цели на улучшение укажите положительное целевое время.")
        elif target_duration_sec is not None:
            raise GoalError("Целевое время допустимо только для улучшения результата.")

    @staticmethod
    async def _require_user(session: AsyncSession, telegram_user_id: int) -> User:
        found = await UserRepository(session).get_by_telegram_id(telegram_user_id)
        if found is None:
            raise GoalError("Сначала выполните /start.")
        return found[0]

    @staticmethod
    def _dto(goal: RunningGoal) -> RunningGoalDto:
        return RunningGoalDto(
            goal.id,
            goal.type,
            goal.status,
            goal.target_date,
            goal.target_duration_sec,
            goal.started_at,
            goal.completed_at,
        )
