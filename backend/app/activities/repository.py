import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    ActivitySummary,
    AggregateStats,
    PotentialDuplicate,
    RunHistoryItem,
)


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

    async def best_distance(self, user_id: uuid.UUID, target_m: int) -> ActivitySummary | None:
        statement = (
            select(Activity)
            .where(
                Activity.user_id == user_id,
                Activity.activity_type == ActivityType.RUN,
                Activity.deleted_at.is_(None),
                Activity.distance_m >= target_m,
                Activity.distance_m <= int(target_m * 1.02),
            )
            .order_by(Activity.avg_pace_sec_per_km, Activity.elapsed_time_sec)
            .limit(1)
        )
        activity = (await self.session.execute(statement)).scalar_one_or_none()
        if activity is None:
            return None
        return ActivitySummary(
            activity_id=activity.id,
            distance_m=activity.distance_m,
            elapsed_time_sec=activity.elapsed_time_sec,
            avg_pace_sec_per_km=activity.avg_pace_sec_per_km,
        )

    async def run_history(
        self, user_id: uuid.UUID, *, started_before: datetime | None = None
    ) -> tuple[RunHistoryItem, ...]:
        statement = select(Activity).where(
            Activity.user_id == user_id,
            Activity.activity_type == ActivityType.RUN,
            Activity.deleted_at.is_(None),
        )
        if started_before is not None:
            statement = statement.where(Activity.started_at <= started_before)
        activities = (
            (await self.session.execute(statement.order_by(Activity.started_at))).scalars().all()
        )
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
            )
            for activity in activities
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
