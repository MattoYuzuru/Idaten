import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.activities.models import Activity, ActivityType
from app.coach.models import RecommendationStatus
from app.coach.repository import CoachRepository


class RecommendationLifecycle:
    async def supersede_current(self, session: AsyncSession, user_id: uuid.UUID) -> None:
        current = await CoachRepository(session).current_recommendation(user_id, for_update=True)
        if current is not None:
            current.status = RecommendationStatus.SUPERSEDED

    async def expire_current(
        self, session: AsyncSession, user_id: uuid.UUID, *, moment: datetime
    ) -> bool:
        current = await CoachRepository(session).current_recommendation(user_id, for_update=True)
        if current is None or self._utc(current.valid_until) > moment:
            return False
        current.status = RecommendationStatus.EXPIRED
        return True

    async def activity_recorded(
        self, session: AsyncSession, user_id: uuid.UUID, activity: Activity
    ) -> RecommendationStatus | None:
        if activity.activity_type != ActivityType.RUN:
            return None
        current = await CoachRepository(session).current_recommendation(user_id, for_update=True)
        if current is None:
            return None
        created_at = self._utc(current.created_at)
        started_at = self._utc(activity.started_at)
        status = (
            RecommendationStatus.CONSUMED
            if started_at > created_at
            else RecommendationStatus.SUPERSEDED
        )
        current.status = status
        return status

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
