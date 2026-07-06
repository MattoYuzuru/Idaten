import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from app.activities.models import ActivityType, SourceType


class ImportError(ValueError):
    def __init__(self, message: str, *, code: str = "IMPORT_ERROR") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class NormalizedSplit:
    index: int
    distance_m: int
    elapsed_time_sec: int
    moving_time_sec: int | None = None


@dataclass(frozen=True, slots=True)
class TrackPoint:
    timestamp: datetime
    latitude: float | None = None
    longitude: float | None = None
    elevation_m: float | None = None
    heart_rate: int | None = None
    speed_mps: float | None = None
    cadence_spm: float | None = None


@dataclass(frozen=True, slots=True)
class NormalizedActivity:
    source_type: SourceType
    activity_type: ActivityType
    started_at: datetime
    timezone: str
    distance_m: int
    elapsed_time_sec: int
    moving_time_sec: int | None = None
    title: str | None = None
    external_id: str | None = None
    avg_hr: int | None = None
    max_hr: int | None = None
    splits: tuple[NormalizedSplit, ...] = ()
    track_points: tuple[TrackPoint, ...] = ()

    def to_draft_json(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type.value,
            "activity_type": self.activity_type.value,
            "started_at": self.started_at.isoformat(),
            "timezone": self.timezone,
            "distance_m": self.distance_m,
            "elapsed_time_sec": self.elapsed_time_sec,
            "moving_time_sec": self.moving_time_sec,
            "title": self.title,
            "external_id": self.external_id,
            "avg_hr": self.avg_hr,
            "max_hr": self.max_hr,
            "splits": [asdict(split) for split in self.splits],
        }

    @classmethod
    def from_draft_json(cls, value: dict[str, Any]) -> "NormalizedActivity":
        splits_value = value.get("splits", [])
        if not isinstance(splits_value, list):
            raise ImportError("Черновик импорта поврежден.", code="INVALID_DRAFT")
        return cls(
            source_type=SourceType(str(value["source_type"])),
            activity_type=ActivityType(str(value["activity_type"])),
            started_at=datetime.fromisoformat(str(value["started_at"])),
            timezone=str(value["timezone"]),
            distance_m=int(value["distance_m"]),
            elapsed_time_sec=int(value["elapsed_time_sec"]),
            moving_time_sec=(
                int(value["moving_time_sec"]) if value.get("moving_time_sec") is not None else None
            ),
            title=str(value["title"]) if value.get("title") is not None else None,
            external_id=(
                str(value["external_id"]) if value.get("external_id") is not None else None
            ),
            avg_hr=int(value["avg_hr"]) if value.get("avg_hr") is not None else None,
            max_hr=int(value["max_hr"]) if value.get("max_hr") is not None else None,
            splits=tuple(
                NormalizedSplit(
                    index=int(item["index"]),
                    distance_m=int(item["distance_m"]),
                    elapsed_time_sec=int(item["elapsed_time_sec"]),
                    moving_time_sec=(
                        int(item["moving_time_sec"])
                        if item.get("moving_time_sec") is not None
                        else None
                    ),
                )
                for item in splits_value
                if isinstance(item, dict)
            ),
        )


@dataclass(frozen=True, slots=True)
class ImportOverrides:
    started_at: datetime | None = None
    distance_m: int | None = None
    elapsed_time_sec: int | None = None
    moving_time_sec: int | None = None
    title: str | None = None


@dataclass(frozen=True, slots=True)
class DuplicateCandidate:
    activity_id: uuid.UUID
    started_at: datetime
    distance_m: int
    elapsed_time_sec: int


@dataclass(frozen=True, slots=True)
class ImportPreview:
    import_id: uuid.UUID
    source_type: SourceType
    started_at: datetime
    distance_m: int
    elapsed_time_sec: int
    title: str | None
    duplicate_candidates: tuple[DuplicateCandidate, ...]
    exact_duplicate_activity_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class ImportHistoryItem:
    import_id: uuid.UUID
    filename: str
    status: str
    source_type: SourceType | None
    created_at: datetime
    activity_id: uuid.UUID | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class ConfirmedImport:
    import_id: uuid.UUID
    activity_id: uuid.UUID
    created: bool
    report_message: str | None


def apply_overrides(
    activity: NormalizedActivity, overrides: ImportOverrides | None
) -> NormalizedActivity:
    if overrides is None:
        return activity
    return NormalizedActivity(
        source_type=activity.source_type,
        activity_type=activity.activity_type,
        started_at=overrides.started_at or activity.started_at,
        timezone=activity.timezone,
        distance_m=(
            overrides.distance_m if overrides.distance_m is not None else activity.distance_m
        ),
        elapsed_time_sec=(
            overrides.elapsed_time_sec
            if overrides.elapsed_time_sec is not None
            else activity.elapsed_time_sec
        ),
        moving_time_sec=(
            overrides.moving_time_sec
            if overrides.moving_time_sec is not None
            else activity.moving_time_sec
        ),
        title=overrides.title if overrides.title is not None else activity.title,
        external_id=activity.external_id,
        avg_hr=activity.avg_hr,
        max_hr=activity.max_hr,
        splits=activity.splits if overrides.distance_m is None else (),
    )


def validate_normalized(activity: NormalizedActivity) -> None:
    if activity.started_at.tzinfo is None:
        raise ImportError("Время старта должно содержать часовой пояс.", code="INVALID_TIMEZONE")
    if activity.distance_m <= 0 or activity.distance_m > 500_000:
        raise ImportError("Расстояние должно быть от 1 м до 500 км.", code="INVALID_DISTANCE")
    if activity.elapsed_time_sec <= 0 or activity.elapsed_time_sec > 7 * 24 * 3600:
        raise ImportError("Некорректная длительность активности.", code="INVALID_DURATION")
    if activity.moving_time_sec is not None and not (
        0 < activity.moving_time_sec <= activity.elapsed_time_sec
    ):
        raise ImportError(
            "Moving time должен быть положительным и не больше elapsed time.",
            code="INVALID_MOVING_TIME",
        )
    if activity.title is not None and len(activity.title) > 255:
        raise ImportError("Название активности слишком длинное.", code="INVALID_TITLE")
    for heart_rate in (activity.avg_hr, activity.max_hr):
        if heart_rate is not None and not 20 <= heart_rate <= 260:
            raise ImportError("Пульс находится вне допустимого диапазона.", code="INVALID_HR")
    if (
        activity.avg_hr is not None
        and activity.max_hr is not None
        and activity.avg_hr > activity.max_hr
    ):
        raise ImportError("Средний пульс не может быть выше максимального.", code="INVALID_HR")
    for expected_index, split in enumerate(activity.splits, start=1):
        if split.index != expected_index or split.distance_m <= 0 or split.elapsed_time_sec <= 0:
            raise ImportError("Некорректные splits.", code="INVALID_SPLITS")
