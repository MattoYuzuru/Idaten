import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.activities.models import SourceType


class ActivityInputError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ManualRunInput:
    distance_m: int
    elapsed_time_sec: int
    started_at: datetime


@dataclass(frozen=True, slots=True)
class ActivitySummary:
    activity_id: uuid.UUID
    distance_m: int
    elapsed_time_sec: int
    avg_pace_sec_per_km: int


@dataclass(frozen=True, slots=True)
class AggregateStats:
    distance_m: int = 0
    run_count: int = 0
    longest_run_m: int = 0


@dataclass(frozen=True, slots=True)
class PersonalRecords:
    best_5k: ActivitySummary | None
    best_10k: ActivitySummary | None


@dataclass(frozen=True, slots=True)
class RecordedRun:
    activity: ActivitySummary
    week_stats: AggregateStats
    report_message: str


@dataclass(frozen=True, slots=True)
class RunHistoryItem:
    started_at: datetime
    distance_m: int
    elapsed_time_sec: int
    avg_pace_sec_per_km: int
    title: str | None
    source_type: SourceType


def parse_distance_km(value: str) -> int:
    normalized = value.strip().replace(",", ".")
    try:
        distance_km = Decimal(normalized)
    except Exception as error:
        raise ActivityInputError("Расстояние должно быть числом, например 10.02.") from error
    distance_m = int((distance_km * 1000).quantize(Decimal("1")))
    if distance_m <= 0 or distance_m > 500_000:
        raise ActivityInputError("Расстояние должно быть от 0.001 до 500 км.")
    return distance_m


def parse_duration(value: str) -> int:
    parts = value.strip().split(":")
    if len(parts) not in (2, 3) or any(not part.isdigit() for part in parts):
        raise ActivityInputError("Время укажите как MM:SS или H:MM:SS.")
    numbers = [int(part) for part in parts]
    if len(numbers) == 2:
        minutes, seconds = numbers
        hours = 0
    else:
        hours, minutes, seconds = numbers
        if minutes >= 60:
            raise ActivityInputError("Минуты в формате H:MM:SS должны быть меньше 60.")
    if seconds >= 60:
        raise ActivityInputError("Секунды должны быть меньше 60.")
    total = hours * 3600 + minutes * 60 + seconds
    if total <= 0 or total > 7 * 24 * 3600:
        raise ActivityInputError("Длительность должна быть больше нуля и не больше 7 дней.")
    return total


def parse_run_command(arguments: str | None, started_at: datetime) -> ManualRunInput:
    parts = arguments.split() if arguments else []
    if len(parts) != 2:
        raise ActivityInputError("Формат команды: /run 10.02 1:02:41")
    return ManualRunInput(
        distance_m=parse_distance_km(parts[0]),
        elapsed_time_sec=parse_duration(parts[1]),
        started_at=started_at,
    )
