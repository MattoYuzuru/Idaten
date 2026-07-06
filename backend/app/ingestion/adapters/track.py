import math
from datetime import UTC, datetime
from itertools import pairwise

from app.activities.models import ActivityType, SourceType
from app.ingestion.schemas import (
    ImportError,
    NormalizedActivity,
    NormalizedSplit,
    TrackPoint,
)

EARTH_RADIUS_M = 6_371_000.0


def parse_timestamp(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ImportError("Файл содержит некорректное время.", code="INVALID_TIMESTAMP") from error
    if parsed.tzinfo is None:
        raise ImportError("Время в файле не содержит часовой пояс.", code="INVALID_TIMESTAMP")
    return parsed.astimezone(UTC)


def haversine_distance(first: TrackPoint, second: TrackPoint) -> float:
    if (
        first.latitude is None
        or first.longitude is None
        or second.latitude is None
        or second.longitude is None
    ):
        return 0.0
    lat1 = math.radians(first.latitude)
    lat2 = math.radians(second.latitude)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(second.longitude - first.longitude)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(value))


def normalize_track(
    *,
    source_type: SourceType,
    points: list[TrackPoint],
    timezone: str,
    activity_type: ActivityType = ActivityType.RUN,
    title: str | None = None,
    external_id: str | None = None,
    declared_distance_m: int | None = None,
    declared_elapsed_sec: int | None = None,
    declared_moving_sec: int | None = None,
    declared_splits: tuple[NormalizedSplit, ...] = (),
) -> NormalizedActivity:
    if len(points) < 2:
        raise ImportError("В треке недостаточно точек.", code="INSUFFICIENT_TRACK")
    ordered = sorted(points, key=lambda point: point.timestamp)
    elapsed = declared_elapsed_sec or round(
        (ordered[-1].timestamp - ordered[0].timestamp).total_seconds()
    )
    calculated_distance = round(
        sum(haversine_distance(first, second) for first, second in pairwise(ordered))
    )
    distance = declared_distance_m or calculated_distance
    if distance <= 0:
        raise ImportError("В треке отсутствует дистанция.", code="MISSING_DISTANCE")
    heart_rates = [point.heart_rate for point in ordered if point.heart_rate is not None]
    splits = declared_splits or build_splits(distance, elapsed)
    return NormalizedActivity(
        source_type=source_type,
        activity_type=activity_type,
        started_at=ordered[0].timestamp,
        timezone=timezone,
        distance_m=distance,
        elapsed_time_sec=elapsed,
        moving_time_sec=declared_moving_sec,
        title=title,
        external_id=external_id,
        avg_hr=round(sum(heart_rates) / len(heart_rates)) if heart_rates else None,
        max_hr=max(heart_rates) if heart_rates else None,
        splits=splits,
        track_points=tuple(ordered),
    )


def build_splits(distance_m: int, elapsed_sec: int) -> tuple[NormalizedSplit, ...]:
    distances = [1_000] * (distance_m // 1_000)
    if distance_m % 1_000:
        distances.append(distance_m % 1_000)
    result: list[NormalizedSplit] = []
    elapsed_so_far = 0
    distance_so_far = 0
    for index, split_distance in enumerate(distances, start=1):
        distance_so_far += split_distance
        remaining_splits = len(distances) - index
        if remaining_splits == 0:
            split_elapsed = elapsed_sec - elapsed_so_far
        else:
            target_elapsed = round(elapsed_sec * distance_so_far / distance_m)
            target_elapsed = min(target_elapsed, elapsed_sec - remaining_splits)
            split_elapsed = max(1, target_elapsed - elapsed_so_far)
        result.append(
            NormalizedSplit(
                index=index,
                distance_m=split_distance,
                elapsed_time_sec=split_elapsed,
            )
        )
        elapsed_so_far += split_elapsed
    return tuple(result)
