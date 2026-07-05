import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.activities.models import Activity, ActivitySource, ActivityType, SourceType
from app.activities.schemas import ActivitySummary, AggregateStats


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
