import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.readiness.models import CheckInPhase, CheckInStatus, ReadinessCheckIn


class ReadinessRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def active_draft(
        self, user_id: uuid.UUID, phase: CheckInPhase, *, for_update: bool = False
    ) -> ReadinessCheckIn | None:
        statement = select(ReadinessCheckIn).where(
            ReadinessCheckIn.user_id == user_id,
            ReadinessCheckIn.phase == phase,
            ReadinessCheckIn.status == CheckInStatus.DRAFT,
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def by_id(
        self, check_in_id: uuid.UUID, *, for_update: bool = False
    ) -> ReadinessCheckIn | None:
        statement = select(ReadinessCheckIn).where(ReadinessCheckIn.id == check_in_id)
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def latest_confirmed(
        self,
        user_id: uuid.UUID,
        phase: CheckInPhase,
        *,
        linked_activity_id: uuid.UUID | None = None,
    ) -> ReadinessCheckIn | None:
        statement = select(ReadinessCheckIn).where(
            ReadinessCheckIn.user_id == user_id,
            ReadinessCheckIn.phase == phase,
            ReadinessCheckIn.status == CheckInStatus.CONFIRMED,
        )
        if linked_activity_id is not None:
            statement = statement.where(ReadinessCheckIn.linked_activity_id == linked_activity_id)
        statement = statement.order_by(ReadinessCheckIn.confirmed_at.desc()).limit(1)
        return (await self.session.execute(statement)).scalar_one_or_none()

    def add(self, check_in: ReadinessCheckIn) -> None:
        self.session.add(check_in)
