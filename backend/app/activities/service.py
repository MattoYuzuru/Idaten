import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.activities.history import group_runs_by_local_date
from app.activities.models import (
    Activity,
    ActivityVisibility,
    CoachReport,
    ManualActivityDraft,
    ManualDraftStatus,
    ReportType,
    SourceType,
)
from app.activities.repository import ActivityRepository
from app.activities.schemas import (
    ActivityInputError,
    ActivitySummary,
    AggregateStats,
    DailyRunGroup,
    ManualDraft,
    ManualRunInput,
    PersonalRecords,
    RecordedRun,
    parse_run_command,
)
from app.analytics.metrics import (
    calculate_pace_sec_per_km,
    calculate_speed_mps,
    format_local_week_period,
    local_week_bounds,
)
from app.coach.report_builder import build_after_run_report
from app.ingestion.adapters.manual import ManualAdapter
from app.ingestion.schemas import validate_normalized
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
        normalized = ManualAdapter().normalize(run, user.timezone)
        validate_normalized(normalized)
        async with self.session_factory.begin() as session:
            return await self._record_manual_run(session, user, run)

    async def record_manual_command(
        self, identity: TelegramIdentity, arguments: str | None, now: datetime
    ) -> RecordedRun:
        user = await self.user_service.register(identity)
        run = parse_run_command(arguments, now, user.timezone)
        async with self.session_factory.begin() as session:
            return await self._record_manual_run(session, user, run)

    async def start_manual_draft(
        self, identity: TelegramIdentity, now: datetime | None = None
    ) -> ManualDraft:
        user = await self.user_service.register(identity)
        moment = now or datetime.now(UTC)
        async with self.session_factory.begin() as session:
            repository = ActivityRepository(session)
            active = await repository.active_manual_draft(user.id)
            if active is not None and self._as_utc(active.expires_at) <= moment:
                active.status = ManualDraftStatus.EXPIRED
                active = None
            if active is None:
                active = ManualActivityDraft(
                    user_id=user.id,
                    timezone=user.timezone,
                    status=ManualDraftStatus.ACTIVE,
                    expires_at=moment + timedelta(hours=24),
                    pending_field="distance",
                )
                session.add(active)
                await session.flush()
            return self._draft_dto(active, moment)

    async def set_manual_draft_field(
        self,
        telegram_user_id: int,
        draft_id: uuid.UUID,
        field: str,
        value: str,
        now: datetime | None = None,
    ) -> ManualDraft:
        moment = now or datetime.now(UTC)
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            draft = await ActivityRepository(session).manual_draft(draft_id, for_update=True)
            self._require_active_draft(draft, user.id, moment)
            assert draft is not None
            self._apply_draft_value(draft, field, value, moment)
            draft.pending_field = None
            draft.version += 1
            run = self._draft_run(draft, moment)
            if draft.distance_m is not None and draft.elapsed_time_sec is not None:
                validate_normalized(ManualAdapter().normalize(run, user.timezone))
            return self._draft_dto(draft, moment)

    async def choose_manual_draft_field(
        self, telegram_user_id: int, draft_id: uuid.UUID, field: str
    ) -> ManualDraft:
        allowed = {
            "distance",
            "elapsed",
            "date",
            "time",
            "moving",
            "hr",
            "max_hr",
            "cadence",
            "elevation",
            "title",
        }
        if field not in allowed:
            raise ActivityInputError("Неизвестное поле черновика.")
        moment = datetime.now(UTC)
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            draft = await ActivityRepository(session).manual_draft(draft_id, for_update=True)
            self._require_active_draft(draft, user.id, moment)
            assert draft is not None
            draft.pending_field = field
            draft.version += 1
            return self._draft_dto(draft, moment)

    async def pending_manual_draft(self, telegram_user_id: int) -> tuple[ManualDraft, str] | None:
        async with self.session_factory() as session:
            user = await self._require_user(session, telegram_user_id)
            draft = await ActivityRepository(session).active_manual_draft(user.id)
            if draft is None or draft.pending_field is None:
                return None
            return self._draft_dto(draft, datetime.now(UTC)), draft.pending_field

    async def attach_manual_draft_message(
        self, telegram_user_id: int, draft_id: uuid.UUID, message_id: int
    ) -> None:
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            draft = await ActivityRepository(session).manual_draft(draft_id, for_update=True)
            self._require_active_draft(draft, user.id, datetime.now(UTC))
            assert draft is not None
            draft.telegram_message_id = message_id

    async def cancel_manual_draft(self, telegram_user_id: int, draft_id: uuid.UUID) -> ManualDraft:
        moment = datetime.now(UTC)
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            draft = await ActivityRepository(session).manual_draft(draft_id, for_update=True)
            if draft is None or draft.user_id != user.id:
                raise ActivityInputError("Черновик не найден.")
            if draft.status == ManualDraftStatus.ACTIVE:
                draft.status = ManualDraftStatus.CANCELLED
                draft.pending_field = None
                draft.version += 1
            return self._draft_dto(draft, moment)

    async def confirm_manual_draft(self, telegram_user_id: int, draft_id: uuid.UUID) -> RecordedRun:
        moment = datetime.now(UTC)
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            draft = await ActivityRepository(session).manual_draft(draft_id, for_update=True)
            if draft is None or draft.user_id != user.id:
                raise ActivityInputError("Черновик не найден.")
            if draft.status == ManualDraftStatus.SAVED and draft.activity_id is not None:
                return await self._recorded_activity(session, draft.activity_id)
            self._require_active_draft(draft, user.id, moment)
            run = self._draft_run(draft, moment)
            if draft.distance_m is None or draft.elapsed_time_sec is None:
                raise ActivityInputError("Укажите дистанцию и длительность.")
            result = await self._record_manual_run(session, user, run)
            draft.status = ManualDraftStatus.SAVED
            draft.activity_id = result.activity.activity_id
            draft.pending_field = None
            draft.version += 1
            return result

    async def run_history(self, telegram_user_id: int) -> tuple[DailyRunGroup, ...]:
        async with self.session_factory() as session:
            user = await self._require_user(session, telegram_user_id)
            runs = await ActivityRepository(session).run_history(user.id)
            return group_runs_by_local_date(runs, user.timezone)

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

    async def _record_manual_run(
        self, session: AsyncSession, user: User, run: ManualRunInput
    ) -> RecordedRun:
        normalized = ManualAdapter().normalize(run, user.timezone)
        validate_normalized(normalized)
        repository = ActivityRepository(session)
        source = await repository.get_or_create_source(user.id, SourceType.MANUAL)
        activity = Activity(
            user_id=user.id,
            source_id=source.id,
            source_type=SourceType.MANUAL,
            activity_type=normalized.activity_type,
            title=normalized.title,
            started_at=normalized.started_at,
            timezone=normalized.timezone,
            distance_m=normalized.distance_m,
            elapsed_time_sec=normalized.elapsed_time_sec,
            moving_time_sec=normalized.moving_time_sec,
            avg_pace_sec_per_km=calculate_pace_sec_per_km(
                normalized.distance_m, normalized.elapsed_time_sec
            ),
            avg_speed_mps=calculate_speed_mps(normalized.distance_m, normalized.elapsed_time_sec),
            avg_hr=normalized.avg_hr,
            max_hr=normalized.max_hr,
            avg_cadence_spm=normalized.avg_cadence_spm,
            elevation_gain_m=normalized.elevation_gain_m,
            visibility=ActivityVisibility.PRIVATE,
        )
        repository.add(activity)
        await session.flush()
        summary = ActivitySummary(
            activity.id,
            activity.distance_m,
            activity.elapsed_time_sec,
            activity.avg_pace_sec_per_km,
        )
        week_start, week_end = local_week_bounds(normalized.started_at, user.timezone)
        week_stats = await repository.aggregate(
            user.id, started_from=week_start, started_before=week_end
        )
        report = build_after_run_report(
            summary,
            week_stats,
            format_local_week_period(week_start, week_end, user.timezone),
        )
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
        return RecordedRun(summary, week_stats, report.message)

    @staticmethod
    async def _recorded_activity(session: AsyncSession, activity_id: uuid.UUID) -> RecordedRun:
        activity = await session.get(Activity, activity_id)
        if activity is None:
            raise ActivityInputError("Сохраненная активность не найдена.")
        report = await session.scalar(
            select(CoachReport).where(CoachReport.activity_id == activity_id)
        )
        if report is None:
            raise ActivityInputError("Отчет активности не найден.")
        summary = ActivitySummary(
            activity.id,
            activity.distance_m,
            activity.elapsed_time_sec,
            activity.avg_pace_sec_per_km,
        )
        return RecordedRun(summary, AggregateStats(), report.message_private)

    @staticmethod
    def _require_active_draft(
        draft: ManualActivityDraft | None, user_id: uuid.UUID, now: datetime
    ) -> None:
        if draft is None or draft.user_id != user_id:
            raise ActivityInputError("Черновик не найден.")
        if draft.status != ManualDraftStatus.ACTIVE:
            raise ActivityInputError("Черновик уже закрыт.")
        if ActivityService._as_utc(draft.expires_at) <= now:
            draft.status = ManualDraftStatus.EXPIRED
            raise ActivityInputError("Черновик истек; начните /run заново.")

    @staticmethod
    def _draft_run(draft: ManualActivityDraft, now: datetime) -> ManualRunInput:
        return ManualRunInput(
            distance_m=draft.distance_m or 0,
            elapsed_time_sec=draft.elapsed_time_sec or 0,
            started_at=draft.started_at or now.astimezone(ZoneInfo(draft.timezone)),
            timezone=draft.timezone,
            moving_time_sec=draft.moving_time_sec,
            avg_hr=draft.avg_hr,
            max_hr=draft.max_hr,
            avg_cadence_spm=draft.avg_cadence_spm,
            elevation_gain_m=draft.elevation_gain_m,
            title=draft.title,
        )

    @staticmethod
    def _draft_dto(draft: ManualActivityDraft, now: datetime) -> ManualDraft:
        return ManualDraft(
            draft.id,
            draft.version,
            draft.expires_at,
            draft.status.value,
            ActivityService._draft_run(draft, now),
            draft.distance_m is not None and draft.elapsed_time_sec is not None,
            draft.telegram_message_id,
        )

    @staticmethod
    def _apply_draft_value(
        draft: ManualActivityDraft, field: str, value: str, now: datetime
    ) -> None:
        from zoneinfo import ZoneInfo

        if field == "distance":
            from app.activities.schemas import parse_distance_km

            draft.distance_m = parse_distance_km(value)
        elif field in {"elapsed", "moving"}:
            from app.activities.schemas import parse_duration

            parsed = parse_duration(value)
            if field == "elapsed":
                draft.elapsed_time_sec = parsed
            else:
                draft.moving_time_sec = parsed
        elif field in {"hr", "max_hr", "cadence", "elevation"}:
            key = {
                "hr": "avg_hr",
                "max_hr": "max_hr",
                "cadence": "avg_cadence_spm",
                "elevation": "elevation_gain_m",
            }[field]
            ranges = {
                "hr": (20, 260),
                "max_hr": (20, 260),
                "cadence": (30, 300),
                "elevation": (0, 20_000),
            }
            try:
                number = int(value)
            except ValueError as error:
                raise ActivityInputError("Введите целое число.") from error
            if not ranges[field][0] <= number <= ranges[field][1]:
                raise ActivityInputError("Значение вне допустимого диапазона.")
            setattr(draft, key, number)
        elif field == "title":
            if not value.strip() or len(value.strip()) > 255:
                raise ActivityInputError("Название: от 1 до 255 символов.")
            draft.title = value.strip()
        elif field in {"date", "time"}:
            local = (draft.started_at or now).astimezone(ZoneInfo(draft.timezone))
            try:
                if field == "date":
                    from datetime import date

                    local = datetime.combine(
                        date.fromisoformat(value), local.timetz(), ZoneInfo(draft.timezone)
                    )
                else:
                    from datetime import time

                    local = datetime.combine(
                        local.date(), time.fromisoformat(value), ZoneInfo(draft.timezone)
                    )
            except ValueError as error:
                raise ActivityInputError("Дата: YYYY-MM-DD, время: HH:MM.") from error
            draft.started_at = local
        else:
            raise ActivityInputError("Неизвестное поле черновика.")

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @staticmethod
    async def _require_user(session: AsyncSession, telegram_user_id: int) -> User:
        found = await UserRepository(session).get_by_telegram_id(telegram_user_id)
        if found is None:
            raise ActivityInputError("Сначала выполните /start.")
        return found[0]
