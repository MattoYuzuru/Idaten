from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.activities.models import (
    Activity,
    ActivityType,
    ActivityVisibility,
    CoachReport,
    ReportType,
    SourceType,
)
from app.activities.repository import ActivityRepository
from app.activities.schemas import (
    ActivityInputError,
    ActivitySummary,
    AggregateStats,
    ManualRunInput,
    PersonalRecords,
    RecordedRun,
)
from app.analytics.metrics import (
    calculate_pace_sec_per_km,
    calculate_speed_mps,
    local_week_bounds,
)
from app.coach.report_builder import build_after_run_report
from app.users.models import User
from app.users.repository import UserRepository
from app.users.schemas import TelegramIdentity
from app.users.service import UserService


class ActivityService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        user_service: UserService,
    ) -> None:
        self.session_factory = session_factory
        self.user_service = user_service

    async def record_manual_run(
        self, identity: TelegramIdentity, run: ManualRunInput
    ) -> RecordedRun:
        user = await self.user_service.register(identity)
        pace = calculate_pace_sec_per_km(run.distance_m, run.elapsed_time_sec)
        speed = calculate_speed_mps(run.distance_m, run.elapsed_time_sec)

        async with self.session_factory.begin() as session:
            repository = ActivityRepository(session)
            source = await repository.get_or_create_source(user.id, SourceType.MANUAL)
            activity = Activity(
                user_id=user.id,
                source_id=source.id,
                source_type=SourceType.MANUAL,
                activity_type=ActivityType.RUN,
                started_at=run.started_at,
                timezone=user.timezone,
                distance_m=run.distance_m,
                elapsed_time_sec=run.elapsed_time_sec,
                avg_pace_sec_per_km=pace,
                avg_speed_mps=speed,
                visibility=ActivityVisibility.PRIVATE,
            )
            repository.add(activity)
            await session.flush()
            summary = ActivitySummary(
                activity_id=activity.id,
                distance_m=activity.distance_m,
                elapsed_time_sec=activity.elapsed_time_sec,
                avg_pace_sec_per_km=activity.avg_pace_sec_per_km,
            )
            week_start, week_end = local_week_bounds(run.started_at, user.timezone)
            week_stats = await repository.aggregate(
                user.id, started_from=week_start, started_before=week_end
            )
            report = build_after_run_report(summary, week_stats)
            session.add(
                CoachReport(
                    user_id=user.id,
                    activity_id=activity.id,
                    report_type=ReportType.AFTER_RUN,
                    facts_json=report.facts_json,
                    rule_result_json=report.rule_result_json,
                    message_private=report.message,
                )
            )
            return RecordedRun(
                activity=summary, week_stats=week_stats, report_message=report.message
            )

    async def stats(self, telegram_user_id: int) -> AggregateStats:
        async with self.session_factory() as session:
            user = await self._require_user(session, telegram_user_id)
            return await ActivityRepository(session).aggregate(user.id)

    async def week(self, telegram_user_id: int, moment: datetime | None = None) -> AggregateStats:
        async with self.session_factory() as session:
            user = await self._require_user(session, telegram_user_id)
            week_start, week_end = local_week_bounds(moment or datetime.now(UTC), user.timezone)
            return await ActivityRepository(session).aggregate(
                user.id, started_from=week_start, started_before=week_end
            )

    async def personal_records(self, telegram_user_id: int) -> PersonalRecords:
        async with self.session_factory() as session:
            user = await self._require_user(session, telegram_user_id)
            repository = ActivityRepository(session)
            return PersonalRecords(
                best_5k=await repository.best_distance(user.id, 5_000),
                best_10k=await repository.best_distance(user.id, 10_000),
            )

    @staticmethod
    async def _require_user(session: AsyncSession, telegram_user_id: int) -> User:
        found = await UserRepository(session).get_by_telegram_id(telegram_user_id)
        if found is None:
            raise ActivityInputError("Сначала выполните /start.")
        return found[0]
