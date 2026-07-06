import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import OutboxStatus, TelegramOutbox
from .repository import HealthConnectRepository

SendPrivateMessage = Callable[[int, str], Awaitable[int]]


class TelegramOutboxService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        retry_seconds: int = 30,
        lease_seconds: int = 60,
        max_attempts: int = 10,
    ) -> None:
        self.session_factory = session_factory
        self.retry_seconds = retry_seconds
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts

    async def deliver_pending(self, send: SendPrivateMessage, *, limit: int = 20) -> int:
        now = datetime.now(UTC)
        async with self.session_factory.begin() as session:
            records = await HealthConnectRepository(session).pending_outbox(
                now,
                lease_before=now,
                limit=limit,
            )
            claimed = tuple(record.id for record in records)
            for record in records:
                record.status = OutboxStatus.PROCESSING
                record.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
                record.attempts += 1

        delivered = 0
        for outbox_id in claimed:
            if await self._deliver_one(outbox_id, send):
                delivered += 1
        return delivered

    async def _deliver_one(self, outbox_id: uuid.UUID, send: SendPrivateMessage) -> bool:
        async with self.session_factory() as session:
            record = await session.get(TelegramOutbox, outbox_id)
            if record is None or record.status != OutboxStatus.PROCESSING:
                return False
            chat_id = record.private_chat_id
            message = record.message_text
        try:
            message_id = await send(chat_id, message)
        except Exception:
            await self._mark_retry(outbox_id)
            return False
        async with self.session_factory.begin() as session:
            record = await session.get(TelegramOutbox, outbox_id, with_for_update=True)
            if record is None or record.status == OutboxStatus.DELIVERED:
                return False
            record.status = OutboxStatus.DELIVERED
            record.delivered_at = datetime.now(UTC)
            record.telegram_message_id = message_id
            record.lease_expires_at = None
            record.last_error_code = None
        return True

    async def _mark_retry(self, outbox_id: uuid.UUID) -> None:
        now = datetime.now(UTC)
        async with self.session_factory.begin() as session:
            record = await session.get(TelegramOutbox, outbox_id, with_for_update=True)
            if record is None or record.status == OutboxStatus.DELIVERED:
                return
            exhausted = record.attempts >= self.max_attempts
            record.status = OutboxStatus.FAILED if exhausted else OutboxStatus.PENDING
            delay = self.retry_seconds * min(2 ** max(record.attempts - 1, 0), 32)
            record.available_at = now + timedelta(seconds=delay)
            record.lease_expires_at = None
            record.last_error_code = (
                "DELIVERY_RETRY_EXHAUSTED" if exhausted else "TELEGRAM_DELIVERY_FAILED"
            )
