import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.activities.models import Activity, SourceType
from app.ingestion.models import ActivityImport, RawArtifact
from app.ingestion.schemas import DuplicateCandidate


class ImportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def artifact_by_hash(self, user_id: uuid.UUID, sha256: str) -> RawArtifact | None:
        result = await self.session.execute(
            select(RawArtifact).where(
                RawArtifact.user_id == user_id,
                RawArtifact.sha256 == sha256,
            )
        )
        return result.scalar_one_or_none()

    async def import_by_artifact(self, artifact_id: uuid.UUID) -> ActivityImport | None:
        result = await self.session.execute(
            select(ActivityImport).where(ActivityImport.raw_artifact_id == artifact_id)
        )
        return result.scalar_one_or_none()

    async def get_import(
        self, import_id: uuid.UUID, user_id: uuid.UUID, *, for_update: bool = False
    ) -> ActivityImport | None:
        statement = select(ActivityImport).where(
            ActivityImport.id == import_id,
            ActivityImport.user_id == user_id,
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def artifact_for_import(self, import_record: ActivityImport) -> RawArtifact:
        artifact = await self.session.get(RawArtifact, import_record.raw_artifact_id)
        if artifact is None:
            raise RuntimeError("Import references missing artifact")
        return artifact

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

    async def duplicate_candidates(
        self,
        user_id: uuid.UUID,
        *,
        started_at: datetime,
        distance_m: int,
        elapsed_time_sec: int,
    ) -> tuple[DuplicateCandidate, ...]:
        result = await self.session.execute(
            select(Activity)
            .where(
                Activity.user_id == user_id,
                Activity.started_at >= started_at - timedelta(minutes=2),
                Activity.started_at <= started_at + timedelta(minutes=2),
                Activity.distance_m >= distance_m - 100,
                Activity.distance_m <= distance_m + 100,
                Activity.elapsed_time_sec >= elapsed_time_sec - 60,
                Activity.elapsed_time_sec <= elapsed_time_sec + 60,
                Activity.deleted_at.is_(None),
            )
            .order_by(Activity.started_at, Activity.id)
        )
        return tuple(
            DuplicateCandidate(
                activity_id=activity.id,
                started_at=activity.started_at,
                distance_m=activity.distance_m,
                elapsed_time_sec=activity.elapsed_time_sec,
            )
            for activity in result.scalars()
        )

    async def history(
        self, user_id: uuid.UUID, *, limit: int = 20
    ) -> list[tuple[ActivityImport, RawArtifact]]:
        rows = await self.session.execute(
            select(ActivityImport, RawArtifact)
            .join(RawArtifact, RawArtifact.id == ActivityImport.raw_artifact_id)
            .where(ActivityImport.user_id == user_id)
            .order_by(ActivityImport.created_at.desc())
            .limit(limit)
        )
        return [(row[0], row[1]) for row in rows]

    def add(self, entity: object) -> None:
        self.session.add(entity)
