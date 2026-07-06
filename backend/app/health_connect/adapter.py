from app.activities.models import ActivityType, SourceType
from app.ingestion.schemas import NormalizedActivity, NormalizedSplit, TrackPoint

from .schemas import HealthConnectRun


class HealthConnectAdapter:
    def normalize(self, run: HealthConnectRun) -> NormalizedActivity:
        return NormalizedActivity(
            source_type=SourceType.HEALTH_CONNECT,
            activity_type=ActivityType.RUN,
            started_at=run.started_at,
            timezone=run.timezone,
            distance_m=run.distance_m,
            elapsed_time_sec=run.elapsed_time_sec,
            moving_time_sec=run.moving_time_sec,
            title=run.title,
            external_id=run.external_id,
            avg_hr=run.avg_hr,
            max_hr=run.max_hr,
            splits=tuple(
                NormalizedSplit(
                    index=split.index,
                    distance_m=split.distance_m,
                    elapsed_time_sec=split.elapsed_time_sec,
                    moving_time_sec=split.moving_time_sec,
                )
                for split in run.splits
            ),
            track_points=tuple(
                TrackPoint(
                    timestamp=sample.timestamp,
                    latitude=sample.latitude,
                    longitude=sample.longitude,
                    elevation_m=sample.elevation_m,
                    heart_rate=sample.heart_rate,
                    speed_mps=sample.speed_mps,
                    cadence_spm=sample.cadence_spm,
                )
                for sample in run.samples
            ),
        )
