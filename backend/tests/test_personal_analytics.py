import uuid
from datetime import UTC, date, datetime, timedelta

from app.analytics.personal import (
    PersonalProgress,
    ProgressTotals,
    ResultCandidate,
    StandardDistance,
    WeeklyProgress,
    progress_bounds,
    select_personal_records,
)
from app.bot.messages import format_personal_records, format_stats


def candidate(
    distance_m: int,
    elapsed_time_sec: int,
    *,
    started_at: datetime = datetime(2026, 7, 8, tzinfo=UTC),
    activity_id: uuid.UUID | None = None,
) -> ResultCandidate:
    return ResultCandidate(
        activity_id=activity_id or uuid.uuid4(),
        started_at=started_at,
        distance_m=distance_m,
        elapsed_time_sec=elapsed_time_sec,
        avg_pace_sec_per_km=round(elapsed_time_sec * 1000 / distance_m),
    )


def test_standard_results_accept_gps_tolerance_and_keep_estimates_separate() -> None:
    five_slow = candidate(4_900, 1_900)
    five_fast = candidate(5_100, 1_850)
    ten = candidate(9_800, 3_700)
    long_run = candidate(11_000, 3_960)
    half = candidate(21_097, 7_800)

    records = select_personal_records((five_slow, long_run, half, ten, five_fast))
    by_distance = {item.distance: item for item in records.results}

    assert by_distance[StandardDistance.FIVE_K].actual == five_fast
    assert by_distance[StandardDistance.TEN_K].actual == ten
    assert by_distance[StandardDistance.HALF_MARATHON].actual == half
    ten_estimate = by_distance[StandardDistance.TEN_K].estimate
    assert ten_estimate is not None
    assert ten_estimate.source_distance_m == 11_000
    assert ten_estimate.estimated_duration_sec == 3_600
    rendered = format_personal_records(records)
    assert "Результаты и оценки" in rendered
    assert "Оценка по средней скорости тренировки" in rendered
    assert "источник 11.00 км" in rendered
    assert "Оценка не является рекордом" in rendered


def test_actual_result_ties_use_target_deviation_then_stable_id() -> None:
    farther = candidate(
        5_050,
        1_800,
        activity_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
    )
    exact_later_id = candidate(
        5_000,
        1_800,
        activity_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
    )

    records = select_personal_records((farther, exact_later_id))

    assert records.best_5k == exact_later_id


def test_progress_bounds_use_local_days_and_eight_calendar_weeks() -> None:
    bounds = progress_bounds(datetime(2026, 7, 5, 21, 30, tzinfo=UTC), "Europe/Moscow")

    assert bounds.current_28_start == datetime(2026, 6, 8, 21, tzinfo=UTC)
    assert bounds.previous_28_start == datetime(2026, 5, 11, 21, tzinfo=UTC)
    assert len(bounds.week_bounds) == 8
    assert bounds.week_bounds[-1][:2] == (
        datetime(2026, 7, 5, 21, tzinfo=UTC),
        datetime(2026, 7, 12, 21, tzinfo=UTC),
    )


def test_progress_message_has_numeric_eight_week_fallback_and_zero_history() -> None:
    start = date(2026, 5, 18)
    weeks = tuple(
        WeeklyProgress(
            start + timedelta(weeks=index),
            start + timedelta(weeks=index, days=7),
            ProgressTotals(distance_m=index * 1_000, run_count=index),
        )
        for index in range(8)
    )
    progress = PersonalProgress(
        all_time=ProgressTotals(),
        current_28_days=ProgressTotals(),
        previous_28_days=ProgressTotals(),
        weeks=weeks,
        usual_weekly_distance_m=0,
    )

    first = format_stats(progress)
    second = format_stats(progress)

    assert first == second
    assert sum(any(bar in line for bar in "▁▂▃▄▅▆▇█") for line in first.splitlines()) == 8
    assert "0.0 км" in first
    assert "пока недостаточно" in first
