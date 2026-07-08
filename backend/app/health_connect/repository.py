import uuid
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.activities.models import Activity
from app.users.models import TelegramAccount

from .models import (
    Device,
    DeviceLinkAttempt,
    DeviceLinkCode,
    HealthConnectSyncBatch,
    OutboxStatus,
    TelegramOutbox,
)


class HealthConnectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def link_code_by_hash(
        self, code_hash: str, *, for_update: bool = False
    ) -> DeviceLinkCode | None:
        statement = select(DeviceLinkCode).where(DeviceLinkCode.code_hash == code_hash)
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def attempts_since(self, key_hash: str, since: datetime) -> int:
        value = await self.session.scalar(
            select(func.count(DeviceLinkAttempt.id)).where(
                DeviceLinkAttempt.attempt_key_hash == key_hash,
                DeviceLinkAttempt.attempted_at >= since,
            )
        )
        return int(value or 0)

    async def device(self, device_id: uuid.UUID, *, for_update: bool = False) -> Device | None:
        statement = select(Device).where(Device.id == device_id)
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def devices_for_user(self, user_id: uuid.UUID) -> tuple[Device, ...]:
        result = await self.session.execute(
            select(Device).where(Device.user_id == user_id).order_by(Device.created_at, Device.id)
        )
        return tuple(result.scalars())

    async def device_by_installation(
        self, user_id: uuid.UUID, installation_id_hash: str
    ) -> Device | None:
        result = await self.session.execute(
            select(Device).where(
                Device.user_id == user_id,
                Device.installation_id_hash == installation_id_hash,
            )
        )
        return result.scalar_one_or_none()

    async def existing_activity(self, user_id: uuid.UUID, external_id: str) -> Activity | None:
        return (
            await self.session.execute(
                select(Activity).where(
                    Activity.user_id == user_id,
                    Activity.source_type == "HEALTH_CONNECT",
                    Activity.external_id == external_id,
                    Activity.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

    async def private_chat_id(self, user_id: uuid.UUID) -> int:
        chat_id = await self.session.scalar(
            select(TelegramAccount.private_chat_id).where(TelegramAccount.user_id == user_id)
        )
        if chat_id is None:
            raise RuntimeError("Device user has no Telegram account")
        return int(chat_id)

    async def sync_batch_by_key(self, batch_key: str) -> HealthConnectSyncBatch | None:
        return (
            await self.session.execute(
                select(HealthConnectSyncBatch).where(HealthConnectSyncBatch.batch_key == batch_key)
            )
        ).scalar_one_or_none()

    async def pending_outbox(
        self, now: datetime, *, lease_before: datetime, limit: int
    ) -> tuple[TelegramOutbox, ...]:
        result = await self.session.execute(
            select(TelegramOutbox)
            .where(
                TelegramOutbox.available_at <= now,
                or_(
                    TelegramOutbox.status == OutboxStatus.PENDING,
                    (
                        (TelegramOutbox.status == OutboxStatus.PROCESSING)
                        & (TelegramOutbox.lease_expires_at <= lease_before)
                    ),
                ),
            )
            .order_by(TelegramOutbox.created_at, TelegramOutbox.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return tuple(result.scalars())

    def add(self, entity: object) -> None:
        self.session.add(entity)
