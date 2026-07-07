import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.groups.models import (
    GroupGoal,
    GroupMonthlyReport,
    GroupReportOutbox,
    MonthlyOutboxStatus,
    RunningGroup,
)
from app.groups.monthly import EligibleGroupRun, MonthlyFacts, calculate_monthly_facts, month_bounds
from app.groups.repository import GroupRepository
from app.groups.schemas import GroupError

SendGroupMessage = Callable[[int, str], Awaitable[int]]


class MonthlyReportService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        retry_seconds: int = 30,
        lease_seconds: int = 60,
        max_attempts: int = 5,
    ) -> None:
        self.session_factory = session_factory
        self.retry_seconds = retry_seconds
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts

    async def current(self, telegram_chat_id: int, moment: datetime) -> MonthlyFacts:
        async with self.session_factory() as session:
            repository = GroupRepository(session)
            group = await repository.get_group_by_chat_id(telegram_chat_id)
            if group is None:
                raise GroupError(
                    "Группа не настроена. Администратор должен выполнить /setup_group."
                )
            start, end = month_bounds(moment, group.timezone)
            return await self._facts(repository, group, start, end)

    async def set_goal(
        self,
        telegram_chat_id: int,
        target_distance_m: int,
        moment: datetime,
        *,
        actor_is_admin: bool,
    ) -> MonthlyFacts:
        if not actor_is_admin:
            raise GroupError("Цель группы может менять только администратор Telegram-чата.")
        if not 1_000 <= target_distance_m <= 10_000_000:
            raise GroupError("Цель должна быть от 1 до 10000 км.")
        async with self.session_factory.begin() as session:
            repository = GroupRepository(session)
            group = await repository.get_group_by_chat_id(telegram_chat_id)
            if group is None:
                raise GroupError(
                    "Группа не настроена. Администратор должен выполнить /setup_group."
                )
            start, end = month_bounds(moment, group.timezone)
            period_start = start.astimezone(ZoneInfo(group.timezone)).date()
            goal = await repository.goal(group.id, period_start)
            if goal is None:
                repository.add(
                    GroupGoal(
                        group_id=group.id,
                        period_start=period_start,
                        target_distance_m=target_distance_m,
                    )
                )
            else:
                goal.target_distance_m = target_distance_m
            await session.flush()
            return await self._facts(repository, group, start, end)

    async def generate_previous_month(self, moment: datetime | None = None) -> int:
        now = moment or datetime.now(UTC)
        async with self.session_factory() as session:
            groups = await GroupRepository(session).groups()
        created = 0
        for group in groups:
            zone = ZoneInfo(group.timezone)
            current_local = now.astimezone(zone)
            current_start = current_local.date().replace(day=1)
            previous_moment = datetime.combine(
                current_start - timedelta(days=1), datetime.min.time(), zone
            ).astimezone(UTC)
            start, end = month_bounds(previous_moment, group.timezone)
            if await self._create_report(group.id, start, end, now):
                created += 1
        return created

    async def _create_report(
        self, group_id: uuid.UUID, start: datetime, end: datetime, now: datetime
    ) -> bool:
        async with self.session_factory.begin() as session:
            repository = GroupRepository(session)
            group = await repository.get_group_by_id(group_id)
            if group is None:
                return False
            period_start = start.astimezone(ZoneInfo(group.timezone)).date()
            if await repository.monthly_report(group.id, period_start) is not None:
                return False
            facts = await self._facts(repository, group, start, end)
            message = format_month(facts, period_start)
            report = GroupMonthlyReport(
                group_id=group.id,
                period_start=period_start,
                report_type="MONTHLY",
                facts_json=facts.as_json(),
                message_text=message,
                created_at=now,
            )
            repository.add(report)
            await session.flush()
            repository.add(
                GroupReportOutbox(
                    report_id=report.id,
                    telegram_chat_id=group.telegram_chat_id,
                    message_text=message,
                    status=MonthlyOutboxStatus.PENDING,
                    attempts=0,
                    available_at=now,
                    created_at=now,
                )
            )
            return True

    async def deliver_pending(self, send: SendGroupMessage, *, limit: int = 20) -> int:
        now = datetime.now(UTC)
        async with self.session_factory.begin() as session:
            records = await GroupRepository(session).pending_monthly_outbox(now, limit=limit)
            claimed = tuple(record.id for record in records)
            for record in records:
                record.status = MonthlyOutboxStatus.PROCESSING
                record.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
                record.attempts += 1
        delivered = 0
        for record_id in claimed:
            if await self._deliver_one(record_id, send):
                delivered += 1
        return delivered

    async def _deliver_one(self, record_id: uuid.UUID, send: SendGroupMessage) -> bool:
        async with self.session_factory() as session:
            record = await GroupRepository(session).monthly_outbox(record_id)
            if record is None or record.status != MonthlyOutboxStatus.PROCESSING:
                return False
            chat_id, message = record.telegram_chat_id, record.message_text
        try:
            message_id = await send(chat_id, message)
        except Exception:
            await self._mark_retry(record_id)
            return False
        async with self.session_factory.begin() as session:
            record = await GroupRepository(session).monthly_outbox_for_update(record_id)
            if record is None or record.status == MonthlyOutboxStatus.DELIVERED:
                return False
            record.status = MonthlyOutboxStatus.DELIVERED
            record.delivered_at = datetime.now(UTC)
            record.telegram_message_id = message_id
            record.lease_expires_at = None
            record.last_error_code = None
        return True

    async def _mark_retry(self, record_id: uuid.UUID) -> None:
        now = datetime.now(UTC)
        async with self.session_factory.begin() as session:
            record = await GroupRepository(session).monthly_outbox_for_update(record_id)
            if record is None or record.status == MonthlyOutboxStatus.DELIVERED:
                return
            exhausted = record.attempts >= self.max_attempts
            record.status = MonthlyOutboxStatus.FAILED if exhausted else MonthlyOutboxStatus.PENDING
            record.available_at = now + timedelta(
                seconds=self.retry_seconds * min(2 ** max(record.attempts - 1, 0), 32)
            )
            record.lease_expires_at = None
            record.last_error_code = "RETRY_EXHAUSTED" if exhausted else "DELIVERY_FAILED"

    @staticmethod
    async def _facts(
        repository: GroupRepository,
        group: RunningGroup,
        start: datetime,
        end: datetime,
    ) -> MonthlyFacts:
        rows = await repository.eligible_activities(
            group.id, started_from=start, started_before=end
        )
        period_start: date = start.astimezone(ZoneInfo(group.timezone)).date()
        goal = await repository.goal(group.id, period_start)
        return calculate_monthly_facts(
            tuple(
                EligibleGroupRun(user.display_name, activity.started_at, activity.distance_m)
                for activity, user in rows
            ),
            timezone=group.timezone,
            goal_distance_m=None if goal is None else goal.target_distance_m,
        )


def format_month(facts: MonthlyFacts, period_start: date | None = None) -> str:
    title = "Месяц группы" if period_start is None else f"Месяц группы · {period_start:%Y-%m}"
    goal = "не задана"
    if facts.goal_distance_m is not None:
        percent = min(999, facts.distance_m * 100 // facts.goal_distance_m)
        goal = f"{facts.distance_m / 1000:.1f}/{facts.goal_distance_m / 1000:.1f} км ({percent}%)"
    return (
        f"{title}\n\nПробежек: {facts.run_count}\nДистанция: {facts.distance_m / 1000:.2f} км\n"
        f"Участников: {facts.members}\nБольше всех: {facts.most_distance or '—'}\n"
        f"Самая длинная: {facts.longest_run or '—'}\nСтабильность: {facts.consistency or '—'}\n"
        f"Парных дней: {facts.pair_runs}\nЦель: {goal}"
    )
