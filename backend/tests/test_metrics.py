from datetime import UTC, datetime

import pytest

from app.analytics.metrics import (
    MetricsError,
    calculate_pace_sec_per_km,
    format_duration,
    format_pace,
    local_week_bounds,
)


def test_calculates_expected_pace() -> None:
    assert calculate_pace_sec_per_km(10_020, 3_761) == 375
    assert format_pace(375) == "6:15"
    assert format_duration(3_761) == "1:02:41"


def test_rejects_invalid_metric_input() -> None:
    with pytest.raises(MetricsError):
        calculate_pace_sec_per_km(0, 100)


def test_week_bounds_use_user_timezone() -> None:
    start, end = local_week_bounds(datetime(2026, 7, 8, 12, tzinfo=UTC), "Europe/Moscow")
    assert start == datetime(2026, 7, 5, 21, tzinfo=UTC)
    assert end == datetime(2026, 7, 12, 21, tzinfo=UTC)
