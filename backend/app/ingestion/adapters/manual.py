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
            timezone=run.timezone or timezone,
            distance_m=run.distance_m,
            elapsed_time_sec=run.elapsed_time_sec,
            moving_time_sec=run.moving_time_sec,
            title=run.title,
            avg_hr=run.avg_hr,
            max_hr=run.max_hr,
            avg_cadence_spm=run.avg_cadence_spm,
            elevation_gain_m=run.elevation_gain_m,
        )
