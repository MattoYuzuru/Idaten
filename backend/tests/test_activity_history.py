import uuid
from datetime import UTC, datetime

from app.activities.history import group_runs_by_local_date
from app.activities.models import SourceType
from app.activities.schemas import RunHistoryItem


def item(started_at: datetime, distance_m: int) -> RunHistoryItem:
    return RunHistoryItem(
        activity_id=uuid.uuid4(),
        started_at=started_at,
        distance_m=distance_m,
        elapsed_time_sec=1_800,
        avg_pace_sec_per_km=360,
        title=None,
        source_type=SourceType.HEALTH_CONNECT,
    )


def test_daily_grouping_uses_local_boundary_and_keeps_sessions() -> None:
    groups = group_runs_by_local_date(
        (
            item(datetime(2026, 6, 16, 22, 30, tzinfo=UTC), 3_000),
            item(datetime(2026, 6, 16, 6, tzinfo=UTC), 5_000),
            item(datetime(2026, 6, 16, 8, tzinfo=UTC), 7_000),
        ),
        "Europe/Moscow",
    )

    assert [group.local_date.isoformat() for group in groups] == ["2026-06-17", "2026-06-16"]
    assert groups[1].run_count == 2
    assert groups[1].distance_m == 12_000
    assert len(groups[1].runs) == 2
