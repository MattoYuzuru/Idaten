import shlex
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.activities.models import SourceType


class ActivityInputError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ManualRunInput:
    distance_m: int
    elapsed_time_sec: int
    started_at: datetime
    timezone: str | None = None
    moving_time_sec: int | None = None
    avg_hr: int | None = None
    max_hr: int | None = None
    avg_cadence_spm: int | None = None
    elevation_gain_m: int | None = None
    title: str | None = None


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
    created: bool = True


@dataclass(frozen=True, slots=True)
class RunHistoryItem:
    activity_id: uuid.UUID
    started_at: datetime
    distance_m: int
    elapsed_time_sec: int
    avg_pace_sec_per_km: int
    title: str | None
    source_type: SourceType


@dataclass(frozen=True, slots=True)
class DailyRunGroup:
    local_date: date
    run_count: int
    distance_m: int
    elapsed_time_sec: int
    runs: tuple[RunHistoryItem, ...]


@dataclass(frozen=True, slots=True)
class ManualDraft:
    draft_id: uuid.UUID
    version: int
    expires_at: datetime
    status: str
    run: ManualRunInput
    complete: bool
    telegram_message_id: int | None


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


def parse_run_command(
    arguments: str | None,
    now: datetime,
    default_timezone: str = "UTC",
) -> ManualRunInput:
    try:
        parts = shlex.split(arguments or "")
    except ValueError as error:
        raise ActivityInputError("Проверьте кавычки в названии пробежки.") from error
    if len(parts) < 2:
        raise ActivityInputError("Формат: /run 10.02 1:02:41 [date=YYYY-MM-DD] [time=HH:MM]")
    values: dict[str, str] = {}
    allowed = {"date", "time", "moving", "hr", "max_hr", "cadence", "elevation", "title", "tz"}
    for part in parts[2:]:
        key, separator, value = part.partition("=")
        if not separator or key not in allowed or not value:
            raise ActivityInputError(f"Неизвестный параметр: {part}. Используйте /help.")
        if key in values:
            raise ActivityInputError(f"Параметр {key} указан повторно.")
        values[key] = value

    timezone = values.get("tz", default_timezone)
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise ActivityInputError("Неизвестный IANA timezone.") from error
    local_now = now.astimezone(zone)
    try:
        local_date = date.fromisoformat(values["date"]) if "date" in values else local_now.date()
        local_time = time.fromisoformat(values["time"]) if "time" in values else local_now.time()
    except ValueError as error:
        raise ActivityInputError("Дата: YYYY-MM-DD, время: HH:MM.") from error
    started_at = datetime.combine(local_date, local_time, zone)
    moving = parse_duration(values["moving"]) if "moving" in values else None
    avg_hr = _optional_int(values, "hr", 20, 260, "Средний пульс")
    max_hr = _optional_int(values, "max_hr", 20, 260, "Максимальный пульс")
    cadence = _optional_int(values, "cadence", 30, 300, "Каденс")
    elevation = _optional_int(values, "elevation", 0, 20_000, "Набор высоты")
    elapsed = parse_duration(parts[1])
    if moving is not None and moving > elapsed:
        raise ActivityInputError("Moving time не может быть больше elapsed time.")
    if avg_hr is not None and max_hr is not None and avg_hr > max_hr:
        raise ActivityInputError("Средний пульс не может быть выше максимального.")
    title = values.get("title")
    if title is not None and len(title) > 255:
        raise ActivityInputError("Название не должно быть длиннее 255 символов.")
    return ManualRunInput(
        distance_m=parse_distance_km(parts[0]),
        elapsed_time_sec=elapsed,
        started_at=started_at,
        timezone=timezone,
        moving_time_sec=moving,
        avg_hr=avg_hr,
        max_hr=max_hr,
        avg_cadence_spm=cadence,
        elevation_gain_m=elevation,
        title=title,
    )


def _optional_int(
    values: dict[str, str], key: str, minimum: int, maximum: int, label: str
) -> int | None:
    if key not in values:
        return None
    try:
        result = int(values[key])
    except ValueError as error:
        raise ActivityInputError(f"{label} должен быть целым числом.") from error
    if not minimum <= result <= maximum:
        raise ActivityInputError(f"{label}: допустимо {minimum}–{maximum}.")
    return result
