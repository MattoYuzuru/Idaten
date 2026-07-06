from defusedxml import ElementTree

from app.activities.models import ActivityType, SourceType
from app.ingestion.adapters.track import normalize_track, parse_timestamp
from app.ingestion.schemas import ImportError, NormalizedActivity, NormalizedSplit, TrackPoint


class TcxAdapter:
    source_type = SourceType.TCX

    def parse(self, content: bytes, timezone: str) -> NormalizedActivity:
        try:
            root = ElementTree.fromstring(content)
        except Exception as error:
            raise ImportError("Не удалось разобрать TCX.", code="TCX_PARSE_ERROR") from error
        activity = root.find(".//{*}Activity")
        if activity is None:
            raise ImportError("TCX не содержит Activity.", code="TCX_MISSING_ACTIVITY")
        activity_id = _text(activity.find("{*}Id"))
        points: list[TrackPoint] = []
        for element in activity.findall(".//{*}Trackpoint"):
            time_value = _text(element.find("{*}Time"))
            if time_value is None:
                raise ImportError("TCX trackpoint не содержит время.", code="TCX_MISSING_TIME")
            points.append(
                TrackPoint(
                    timestamp=parse_timestamp(time_value),
                    latitude=_float(element.find(".//{*}LatitudeDegrees")),
                    longitude=_float(element.find(".//{*}LongitudeDegrees")),
                    elevation_m=_float(element.find("{*}AltitudeMeters")),
                    heart_rate=_int(element.find(".//{*}HeartRateBpm/{*}Value")),
                )
            )
        splits: list[NormalizedSplit] = []
        for index, lap in enumerate(activity.findall("{*}Lap"), start=1):
            distance = _float(lap.find("{*}DistanceMeters"))
            elapsed = _float(lap.find("{*}TotalTimeSeconds"))
            if distance is not None and elapsed is not None:
                splits.append(NormalizedSplit(index, round(distance), max(1, round(elapsed))))
        declared_distance = sum(split.distance_m for split in splits) or None
        declared_elapsed = sum(split.elapsed_time_sec for split in splits) or None
        sport = activity.attrib.get("Sport", "Running").lower()
        activity_type = ActivityType.RUN if sport == "running" else ActivityType.OTHER
        return normalize_track(
            source_type=self.source_type,
            points=points,
            timezone=timezone,
            activity_type=activity_type,
            external_id=activity_id,
            declared_distance_m=declared_distance,
            declared_elapsed_sec=declared_elapsed,
            declared_splits=tuple(splits),
        )


def _text(element: object) -> str | None:
    text = getattr(element, "text", None)
    return str(text).strip() if text else None


def _float(element: object) -> float | None:
    value = _text(element)
    return float(value) if value is not None else None


def _int(element: object) -> int | None:
    value = _text(element)
    return int(value) if value is not None else None
