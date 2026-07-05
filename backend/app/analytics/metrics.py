from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class MetricsError(ValueError):
    pass


def calculate_pace_sec_per_km(distance_m: int, duration_sec: int) -> int:
    if distance_m <= 0:
        raise MetricsError("Расстояние должно быть больше нуля.")
    if duration_sec <= 0:
        raise MetricsError("Время должно быть больше нуля.")
    return (duration_sec * 1000 + distance_m // 2) // distance_m


def calculate_speed_mps(distance_m: int, duration_sec: int) -> float:
    if distance_m <= 0 or duration_sec <= 0:
        raise MetricsError("Расстояние и время должны быть больше нуля.")
    return distance_m / duration_sec


def format_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_pace(seconds_per_km: int) -> str:
    minutes, seconds = divmod(seconds_per_km, 60)
    return f"{minutes}:{seconds:02d}"


def local_week_bounds(moment: datetime, timezone_name: str) -> tuple[datetime, datetime]:
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise MetricsError(f"Неизвестный часовой пояс: {timezone_name}") from error

    aware_moment = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    local_moment = aware_moment.astimezone(timezone)
    local_start = (local_moment - timedelta(days=local_moment.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return local_start.astimezone(UTC), (local_start + timedelta(days=7)).astimezone(UTC)
