import io
from datetime import UTC, datetime, timedelta
from typing import Any

import fitdecode  # type: ignore[import-untyped]

from app.activities.models import ActivityType, SourceType
from app.ingestion.adapters.track import normalize_track
from app.ingestion.schemas import ImportError, NormalizedActivity, NormalizedSplit, TrackPoint


class FitAdapter:
    source_type = SourceType.FIT

    def parse(self, content: bytes, timezone: str) -> NormalizedActivity:
        session: dict[str, Any] = {}
        points: list[TrackPoint] = []
        splits: list[NormalizedSplit] = []
        try:
            with fitdecode.FitReader(
                io.BytesIO(content), check_crc=fitdecode.CrcCheck.RAISE
            ) as reader:
                for frame in reader:
                    if not isinstance(frame, fitdecode.FitDataMessage):
                        continue
                    if frame.name == "session":
                        session = _message_values(frame)
                    elif frame.name == "record":
                        point = self._point(_message_values(frame))
                        if point is not None:
                            points.append(point)
                    elif frame.name == "lap":
                        values = _message_values(frame)
                        distance = _number(values.get("total_distance"))
                        elapsed = _number(values.get("total_elapsed_time"))
                        if distance is not None and elapsed is not None:
                            splits.append(
                                NormalizedSplit(
                                    index=len(splits) + 1,
                                    distance_m=round(distance),
                                    elapsed_time_sec=max(1, round(elapsed)),
                                )
                            )
        except Exception as error:
            raise ImportError("Не удалось разобрать FIT.", code="FIT_PARSE_ERROR") from error
        start = _datetime(session.get("start_time"))
        elapsed = _number(session.get("total_elapsed_time"))
        distance = _number(session.get("total_distance"))
        if start is None or elapsed is None or distance is None:
            raise ImportError("FIT не содержит session summary.", code="FIT_MISSING_SESSION")
        if not points:
            points = [TrackPoint(start), TrackPoint(start + timedelta(seconds=elapsed))]
        sport = str(session.get("sport", "running")).lower()
        activity_type = ActivityType.RUN if sport == "running" else ActivityType.OTHER
        normalized = normalize_track(
            source_type=self.source_type,
            points=points,
            timezone=timezone,
            activity_type=activity_type,
            external_id=start.isoformat(),
            declared_distance_m=round(distance),
            declared_elapsed_sec=round(elapsed),
            declared_moving_sec=_round_optional(session.get("total_timer_time")),
            declared_splits=tuple(splits),
        )
        return NormalizedActivity(
            source_type=normalized.source_type,
            activity_type=normalized.activity_type,
            started_at=normalized.started_at,
            timezone=normalized.timezone,
            distance_m=normalized.distance_m,
            elapsed_time_sec=normalized.elapsed_time_sec,
            moving_time_sec=normalized.moving_time_sec,
            external_id=normalized.external_id,
            avg_hr=_round_optional(session.get("avg_heart_rate")),
            max_hr=_round_optional(session.get("max_heart_rate")),
            splits=normalized.splits,
            track_points=tuple(points)
            if any(point.latitude is not None for point in points)
            else (),
        )

    @staticmethod
    def _point(values: dict[str, Any]) -> TrackPoint | None:
        timestamp = _datetime(values.get("timestamp"))
        if timestamp is None:
            return None
        return TrackPoint(
            timestamp=timestamp,
            latitude=_number(values.get("position_lat")),
            longitude=_number(values.get("position_long")),
            elevation_m=_number(values.get("altitude")),
            heart_rate=_round_optional(values.get("heart_rate")),
        )


def _datetime(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _message_values(frame: Any) -> dict[str, Any]:
    return {
        str(field.name): field.value
        for field in frame.fields
        if getattr(field, "name", None) is not None
    }


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _round_optional(value: object) -> int | None:
    number = _number(value)
    return round(number) if number is not None else None
