from collections import defaultdict
from dataclasses import replace
from datetime import date
from zoneinfo import ZoneInfo

from app.activities.schemas import DailyRunGroup, RunHistoryItem


def group_runs_by_local_date(
    runs: tuple[RunHistoryItem, ...], timezone: str
) -> tuple[DailyRunGroup, ...]:
    grouped: dict[date, list[RunHistoryItem]] = defaultdict(list)
    zone = ZoneInfo(timezone)
    for run in sorted(runs, key=lambda item: (item.started_at, item.activity_id)):
        local_run = replace(run, started_at=run.started_at.astimezone(zone))
        grouped[local_run.started_at.date()].append(local_run)
    return tuple(
        DailyRunGroup(
            local_date=local_date,
            run_count=len(items),
            distance_m=sum(item.distance_m for item in items),
            elapsed_time_sec=sum(item.elapsed_time_sec for item in items),
            runs=tuple(items),
        )
        for local_date, items in sorted(grouped.items(), reverse=True)
    )
