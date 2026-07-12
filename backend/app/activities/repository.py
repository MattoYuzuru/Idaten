import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.activities.duplicates import duplicate_tolerance, metrics_match
from app.activities.models import (
    Activity,
    ActivitySource,
    ActivityType,
    ManualActivityDraft,
    ManualDraftStatus,
    SourceType,
)
from app.activities.schemas import (
    AggregateStats,
    PotentialDuplicate,
    RunHistoryItem,
)
from app.analytics.personal import (
    PersonalProgress,
    ProgressBounds,
    ProgressTotals,
    ResultCandidate,
    WeeklyProgress,
)
from app.readiness.domain import CheckInPhase, CheckInStatus
from app.readiness.models import ReadinessCheckIn


class ActivityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create_source(
        self, user_id: uuid.UUID, source_type: SourceType
    ) -> ActivitySource:
        statement = select(ActivitySource).where(
            ActivitySource.user_id == user_id,
            ActivitySource.source_type == source_type,
        )
        source = (await self.session.execute(statement)).scalar_one_or_none()
        if source:
            return source
        source = ActivitySource(user_id=user_id, source_type=source_type)
        self.session.add(source)
        await self.session.flush()
        return source

    async def exact_activity(
        self, user_id: uuid.UUID, source_type: SourceType, external_id: str | None
    ) -> Activity | None:
        if external_id is None:
            return None
        result = await self.session.execute(
            select(Activity).where(
                Activity.user_id == user_id,
                Activity.source_type == source_type,
                Activity.external_id == external_id,
                Activity.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    def add(self, activity: Activity) -> None:
        self.session.add(activity)

    async def aggregate(
        self,
        user_id: uuid.UUID,
        *,
        started_from: datetime | None = None,
        started_before: datetime | None = None,
    ) -> AggregateStats:
        statement = select(
            func.coalesce(func.sum(Activity.distance_m), 0),
            func.count(Activity.id),
            func.coalesce(func.max(Activity.distance_m), 0),
        ).where(
            Activity.user_id == user_id,
            Activity.activity_type == ActivityType.RUN,
            Activity.deleted_at.is_(None),
        )
        if started_from is not None:
            statement = statement.where(Activity.started_at >= started_from)
        if started_before is not None:
            statement = statement.where(Activity.started_at < started_before)
        row = (await self.session.execute(statement)).one()
        return AggregateStats(
            distance_m=int(row[0]), run_count=int(row[1]), longest_run_m=int(row[2])
        )

    async def result_candidates(self, user_id: uuid.UUID) -> tuple[ResultCandidate, ...]:
        rows = await self.session.execute(
            select(
                Activity.id,
                Activity.started_at,
                Activity.distance_m,
                Activity.elapsed_time_sec,
                Activity.avg_pace_sec_per_km,
            ).where(
                Activity.user_id == user_id,
                Activity.activity_type == ActivityType.RUN,
                Activity.deleted_at.is_(None),
            )
        )
        return tuple(ResultCandidate(*row) for row in rows.tuples())

    async def personal_progress(
        self, user_id: uuid.UUID, bounds: ProgressBounds
    ) -> PersonalProgress:
        windows = (
            (None, bounds.as_of),
            (bounds.current_28_start, bounds.as_of),
            (bounds.previous_28_start, bounds.current_28_start),
            *((start, min(end, bounds.as_of)) for start, end, _label, _end in bounds.week_bounds),
        )
        columns: list[ColumnElement[int]] = []
        for start, end in windows:
            condition = Activity.started_at < end
            if start is not None:
                condition = condition & (Activity.started_at >= start)
            columns.extend(
                (
                    func.coalesce(func.sum(case((condition, Activity.distance_m), else_=0)), 0),
                    func.coalesce(func.sum(case((condition, 1), else_=0)), 0),
                    func.coalesce(func.max(case((condition, Activity.distance_m), else_=0)), 0),
                    func.coalesce(
                        func.sum(case((condition, Activity.elapsed_time_sec), else_=0)), 0
                    ),
                )
            )
        statement = select(*columns).where(
            Activity.user_id == user_id,
            Activity.activity_type == ActivityType.RUN,
            Activity.deleted_at.is_(None),
        )
        row = (await self.session.execute(statement)).one()
        totals = tuple(
            ProgressTotals(*(int(value) for value in row[index : index + 4]))
            for index in range(0, len(row), 4)
        )
        weeks = tuple(
            WeeklyProgress(starts_on, ends_on, total)
            for (*_utc, starts_on, ends_on), total in zip(
                bounds.week_bounds, totals[3:], strict=True
            )
        )
        completed_baseline = weeks[-5:-1]
        usual_weekly_distance_m = sum(item.totals.distance_m for item in completed_baseline) // len(
            completed_baseline
        )
        return PersonalProgress(
            all_time=totals[0],
            current_28_days=totals[1],
            previous_28_days=totals[2],
            weeks=weeks,
            usual_weekly_distance_m=usual_weekly_distance_m,
        )

    async def run_history(
        self, user_id: uuid.UUID, *, started_before: datetime | None = None
    ) -> tuple[RunHistoryItem, ...]:
        session_rpe = (
            select(ReadinessCheckIn.session_rpe)
            .where(
                ReadinessCheckIn.linked_activity_id == Activity.id,
                ReadinessCheckIn.phase == CheckInPhase.POST_RUN,
                ReadinessCheckIn.status == CheckInStatus.CONFIRMED,
                ReadinessCheckIn.session_rpe.is_not(None),
            )
            .order_by(ReadinessCheckIn.confirmed_at.desc(), ReadinessCheckIn.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        statement = select(Activity, session_rpe).where(
            Activity.user_id == user_id,
            Activity.activity_type == ActivityType.RUN,
            Activity.deleted_at.is_(None),
        )
        if started_before is not None:
            statement = statement.where(Activity.started_at <= started_before)
        rows = (
            await self.session.execute(statement.order_by(Activity.started_at, Activity.id))
        ).all()
        return tuple(
            RunHistoryItem(
                activity_id=activity.id,
                started_at=activity.started_at,
                distance_m=activity.distance_m,
                elapsed_time_sec=activity.elapsed_time_sec,
                avg_pace_sec_per_km=activity.avg_pace_sec_per_km,
                title=activity.title,
                source_type=activity.source_type,
                start_time_known=activity.start_time_known,
                moving_time_sec=activity.moving_time_sec,
                avg_hr=activity.avg_hr,
                max_hr=activity.max_hr,
                avg_cadence_spm=activity.avg_cadence_spm,
                elevation_gain_m=activity.elevation_gain_m,
                session_rpe=rpe,
            )
            for activity, rpe in rows
        )

    async def active_manual_draft(self, user_id: uuid.UUID) -> ManualActivityDraft | None:
        return (
            await self.session.execute(
                select(ManualActivityDraft).where(
                    ManualActivityDraft.user_id == user_id,
                    ManualActivityDraft.status == ManualDraftStatus.ACTIVE,
                )
            )
        ).scalar_one_or_none()

    async def duplicate_candidates(
        self,
        user_id: uuid.UUID,
        *,
        local_date: date,
        timezone: str,
        distance_m: int,
        elapsed_time_sec: int,
    ) -> tuple[PotentialDuplicate, ...]:
        zone = ZoneInfo(timezone)
        started_from = datetime.combine(local_date, time.min, zone).astimezone(UTC)
        started_before = datetime.combine(
            local_date + timedelta(days=1), time.min, zone
        ).astimezone(UTC)
        tolerance = duplicate_tolerance(distance_m, elapsed_time_sec)
        statement = (
            select(Activity)
            .where(
                Activity.user_id == user_id,
                Activity.started_at >= started_from,
                Activity.started_at < started_before,
                or_(
                    Activity.distance_m.between(
                        distance_m - tolerance.distance_m,
                        distance_m + tolerance.distance_m,
                    ),
                    Activity.elapsed_time_sec.between(
                        elapsed_time_sec - tolerance.elapsed_time_sec,
                        elapsed_time_sec + tolerance.elapsed_time_sec,
                    ),
                ),
                Activity.deleted_at.is_(None),
            )
            .order_by(Activity.started_at, Activity.id)
        )
        activities = (await self.session.execute(statement)).scalars().all()
        candidates: list[PotentialDuplicate] = []
        for activity in activities:
            distance_matches, duration_matches = metrics_match(
                existing_distance_m=activity.distance_m,
                existing_elapsed_time_sec=activity.elapsed_time_sec,
                distance_m=distance_m,
                elapsed_time_sec=elapsed_time_sec,
            )
            candidates.append(
                PotentialDuplicate(
                    activity_id=activity.id,
                    started_at=activity.started_at,
                    distance_m=activity.distance_m,
                    elapsed_time_sec=activity.elapsed_time_sec,
                    distance_matches=distance_matches,
                    duration_matches=duration_matches,
                )
            )
        return tuple(candidates)

    async def manual_draft(
        self, draft_id: uuid.UUID, *, for_update: bool = False
    ) -> ManualActivityDraft | None:
        statement = select(ManualActivityDraft).where(ManualActivityDraft.id == draft_id)
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()
