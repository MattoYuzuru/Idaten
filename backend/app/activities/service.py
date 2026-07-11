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
    DraftInputMethod,
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
    PossibleDuplicateError,
    PotentialDuplicate,
    RecordedRun,
    parse_run_command,
)
from app.analytics.metrics import (
    calculate_pace_sec_per_km,
    calculate_speed_mps,
    format_local_week_period,
    local_week_bounds,
)
from app.analytics.personal import (
    PersonalProgress,
    PersonalRecords,
    progress_bounds,
    select_personal_records,
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
        self,
        identity: TelegramIdentity,
        run: ManualRunInput,
        *,
        accept_possible_duplicate: bool = False,
    ) -> RecordedRun:
        user = await self.user_service.register(identity)
        normalized = ManualAdapter().normalize(run, user.timezone)
        validate_normalized(normalized)
        async with self.session_factory.begin() as session:
            candidates = await self._run_duplicates(session, user, run)
            if candidates and not accept_possible_duplicate:
                raise PossibleDuplicateError(candidates, run=run)
            return await self._record_manual_run(session, user, run)

    async def record_manual_command(
        self,
        identity: TelegramIdentity,
        arguments: str | None,
        now: datetime,
        *,
        accept_possible_duplicate: bool = False,
    ) -> RecordedRun:
        user = await self.user_service.register(identity)
        run = parse_run_command(arguments, now, user.timezone)
        async with self.session_factory.begin() as session:
            candidates = await self._run_duplicates(session, user, run)
            if candidates and not accept_possible_duplicate:
                raise PossibleDuplicateError(candidates, run=run)
            return await self._record_manual_run(session, user, run)

    async def start_manual_draft(
        self,
        identity: TelegramIdentity,
        now: datetime | None = None,
        *,
        prefill: ManualRunInput | None = None,
    ) -> ManualDraft:
        user = await self.user_service.register(identity)
        moment = now or datetime.now(UTC)
        async with self.session_factory.begin() as session:
            repository = ActivityRepository(session)
            active = await repository.active_manual_draft(user.id)
            if active is not None and self._as_utc(active.expires_at) <= moment:
                active.status = ManualDraftStatus.EXPIRED
                await session.flush()
                active = None
            if active is not None and prefill is not None:
                active.status = ManualDraftStatus.CANCELLED
                active = None
            if active is None:
                active = ManualActivityDraft(
                    user_id=user.id,
                    timezone=user.timezone,
                    status=ManualDraftStatus.ACTIVE,
                    expires_at=moment + timedelta(hours=24),
                    input_method=DraftInputMethod.STEPS,
                    source_type=SourceType.MANUAL,
                    pending_field=None if prefill is not None else "distance",
                    distance_m=prefill.distance_m if prefill is not None else None,
                    elapsed_time_sec=(prefill.elapsed_time_sec if prefill is not None else None),
                    moving_time_sec=(prefill.moving_time_sec if prefill is not None else None),
                    started_at=prefill.started_at if prefill is not None else None,
                    avg_hr=prefill.avg_hr if prefill is not None else None,
                    max_hr=prefill.max_hr if prefill is not None else None,
                    avg_cadence_spm=(prefill.avg_cadence_spm if prefill is not None else None),
                    elevation_gain_m=(prefill.elevation_gain_m if prefill is not None else None),
                    title=prefill.title if prefill is not None else None,
                )
                session.add(active)
                await session.flush()
            return await self._draft_dto(session, active, user, moment)

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
            return await self._draft_dto(session, draft, user, moment)

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
            return await self._draft_dto(session, draft, user, moment)

    async def pending_manual_draft(self, telegram_user_id: int) -> tuple[ManualDraft, str] | None:
        async with self.session_factory() as session:
            user = await self._require_user(session, telegram_user_id)
            draft = await ActivityRepository(session).active_manual_draft(user.id)
            if draft is None or draft.pending_field is None:
                return None
            return (
                await self._draft_dto(session, draft, user, datetime.now(UTC)),
                draft.pending_field,
            )

    async def manual_draft(self, telegram_user_id: int, draft_id: uuid.UUID) -> ManualDraft:
        async with self.session_factory() as session:
            user = await self._require_user(session, telegram_user_id)
            draft = await ActivityRepository(session).manual_draft(draft_id)
            if draft is None or draft.user_id != user.id:
                raise ActivityInputError("Черновик не найден.")
            return await self._draft_dto(session, draft, user, datetime.now(UTC))

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
            return await self._draft_dto(session, draft, user, moment)

    async def confirm_manual_draft(
        self,
        telegram_user_id: int,
        draft_id: uuid.UUID,
        *,
        accept_possible_duplicate: bool = False,
    ) -> RecordedRun:
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
            if not draft.date_confirmed:
                raise ActivityInputError("Укажите дату пробежки.")
            external_id = (
                f"sha256:{draft.input_sha256}"
                if draft.source_type == SourceType.SCREENSHOT and draft.input_sha256
                else None
            )
            exact = await ActivityRepository(session).exact_activity(
                user.id, draft.source_type, external_id
            )
            if exact is not None:
                draft.status = ManualDraftStatus.SAVED
                draft.activity_id = exact.id
                draft.pending_field = None
                draft.version += 1
                return await self._recorded_activity(session, exact.id)
            candidates = await self._run_duplicates(session, user, run)
            if candidates and not accept_possible_duplicate:
                raise PossibleDuplicateError(candidates, run=run)
            result = await self._record_manual_run(
                session,
                user,
                run,
                source_type=draft.source_type,
                start_time_known=draft.start_time_known,
                external_id=external_id,
            )
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

    async def stats(
        self, telegram_user_id: int, moment: datetime | None = None
    ) -> PersonalProgress:
        async with self.session_factory() as session:
            user = await self._require_user(session, telegram_user_id)
            bounds = progress_bounds(moment or datetime.now(UTC), user.timezone)
            return await ActivityRepository(session).personal_progress(user.id, bounds)

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
            candidates = await ActivityRepository(session).result_candidates(user.id)
            return select_personal_records(candidates)

    async def _record_manual_run(
        self,
        session: AsyncSession,
        user: User,
        run: ManualRunInput,
        *,
        source_type: SourceType = SourceType.MANUAL,
        start_time_known: bool = True,
        external_id: str | None = None,
    ) -> RecordedRun:
        normalized = ManualAdapter().normalize(run, user.timezone)
        validate_normalized(normalized)
        repository = ActivityRepository(session)
        source = await repository.get_or_create_source(user.id, source_type)
        activity = Activity(
            user_id=user.id,
            source_id=source.id,
            source_type=source_type,
            external_id=external_id,
            activity_type=normalized.activity_type,
            title=normalized.title,
            started_at=normalized.started_at,
            start_time_known=start_time_known,
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
        return RecordedRun(summary, AggregateStats(), report.message_private, created=False)

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
        started_at = draft.started_at or now.astimezone(ZoneInfo(draft.timezone))
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=ZoneInfo(draft.timezone))
        return ManualRunInput(
            distance_m=draft.distance_m or 0,
            elapsed_time_sec=draft.elapsed_time_sec or 0,
            started_at=started_at,
            timezone=draft.timezone,
            moving_time_sec=draft.moving_time_sec,
            avg_hr=draft.avg_hr,
            max_hr=draft.max_hr,
            avg_cadence_spm=draft.avg_cadence_spm,
            elevation_gain_m=draft.elevation_gain_m,
            title=draft.title,
        )

    async def _draft_dto(
        self, session: AsyncSession, draft: ManualActivityDraft, user: User, now: datetime
    ) -> ManualDraft:
        duplicates: tuple[PotentialDuplicate, ...] = ()
        if (
            draft.distance_m is not None
            and draft.elapsed_time_sec is not None
            and draft.date_confirmed
        ):
            duplicates = await self._run_duplicates(session, user, self._draft_run(draft, now))
        return ManualDraft(
            draft.id,
            draft.version,
            draft.expires_at,
            draft.status.value,
            ActivityService._draft_run(draft, now),
            draft.distance_m is not None
            and draft.elapsed_time_sec is not None
            and draft.date_confirmed,
            draft.telegram_message_id,
            draft.input_method,
            draft.source_type,
            draft.date_confirmed,
            draft.start_time_known,
            duplicates,
        )

    @staticmethod
    async def _run_duplicates(
        session: AsyncSession, user: User, run: ManualRunInput
    ) -> tuple[PotentialDuplicate, ...]:
        timezone = run.timezone or user.timezone
        local_date = run.started_at.astimezone(ZoneInfo(timezone)).date()
        return await ActivityRepository(session).duplicate_candidates(
            user.id,
            local_date=local_date,
            timezone=timezone,
            distance_m=run.distance_m,
            elapsed_time_sec=run.elapsed_time_sec,
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
            draft_timezone = ZoneInfo(draft.timezone)
            local = draft.started_at or now
            # SQLite returns timezone-aware columns as naive datetimes. Treat that
            # value as the draft's declared local time instead of converting it
            # from the host timezone, which would shift an extracted time in CI.
            if local.tzinfo is None:
                local = local.replace(tzinfo=draft_timezone)
            local = local.astimezone(draft_timezone)
            try:
                if field == "date":
                    from datetime import date

                    local = datetime.combine(
                        date.fromisoformat(value), local.timetz(), draft_timezone
                    )
                    draft.date_confirmed = True
                else:
                    from datetime import time

                    local = datetime.combine(
                        local.date(), time.fromisoformat(value), draft_timezone
                    )
                    draft.start_time_known = True
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
