from app.activities.models import ActivityType, SourceType
from app.activities.schemas import ManualRunInput
from app.ingestion.schemas import NormalizedActivity


class ManualAdapter:
    source_type = SourceType.MANUAL

    def normalize(self, run: ManualRunInput, timezone: str) -> NormalizedActivity:
        return NormalizedActivity(
            source_type=self.source_type,
            activity_type=ActivityType.RUN,
            started_at=run.started_at,
            timezone=timezone,
            distance_m=run.distance_m,
            elapsed_time_sec=run.elapsed_time_sec,
        )
