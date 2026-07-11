import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assisted.models import AssistedAccess, ExtractionAttempt, ExtractionAttemptStatus


class AssistedRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def access(
        self, user_id: uuid.UUID, *, for_update: bool = False
    ) -> AssistedAccess | None:
        statement = select(AssistedAccess).where(AssistedAccess.user_id == user_id)
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def successful_attempt(
        self, draft_id: uuid.UUID, input_sha256: str
    ) -> ExtractionAttempt | None:
        statement = select(ExtractionAttempt).where(
            ExtractionAttempt.draft_id == draft_id,
            ExtractionAttempt.input_sha256 == input_sha256,
            ExtractionAttempt.status == ExtractionAttemptStatus.SUCCEEDED,
        )
        statement = statement.order_by(ExtractionAttempt.created_at.desc()).limit(1)
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def attempt_by_id(
        self, attempt_id: uuid.UUID, *, for_update: bool = False
    ) -> ExtractionAttempt | None:
        statement = select(ExtractionAttempt).where(ExtractionAttempt.id == attempt_id)
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def user_attempt_count(
        self, user_id: uuid.UUID, *, started_from: datetime, started_before: datetime
    ) -> int:
        value = await self.session.scalar(
            select(func.count(ExtractionAttempt.id)).where(
                ExtractionAttempt.user_id == user_id,
                ExtractionAttempt.created_at >= started_from,
                ExtractionAttempt.created_at < started_before,
            )
        )
        return int(value or 0)

    async def global_attempt_count(
        self, *, started_from: datetime, started_before: datetime
    ) -> int:
        value = await self.session.scalar(
            select(func.count(ExtractionAttempt.id)).where(
                ExtractionAttempt.created_at >= started_from,
                ExtractionAttempt.created_at < started_before,
            )
        )
        return int(value or 0)

    def add(self, entity: object) -> None:
        self.session.add(entity)
