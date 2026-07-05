from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo


def consecutive_week_streak(
    activity_times: Iterable[datetime], timezone: str, moment: datetime
) -> int:
    zone = ZoneInfo(timezone)
    weeks = {_week_start(_aware(value).astimezone(zone).date()) for value in activity_times}
    current_week = _week_start(_aware(moment).astimezone(zone).date())
    cursor = current_week if current_week in weeks else current_week - timedelta(days=7)
    streak = 0
    while cursor in weeks:
        streak += 1
        cursor -= timedelta(days=7)
    return streak


def _week_start(value: date) -> date:
    return value - timedelta(days=value.weekday())


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
