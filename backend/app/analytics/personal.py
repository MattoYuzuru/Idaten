from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.activities.standards import STANDARD_DISTANCES, StandardDistance, is_actual_distance


@dataclass(frozen=True, slots=True)
class ResultCandidate:
    activity_id: uuid.UUID
    started_at: datetime
    distance_m: int
    elapsed_time_sec: int
    avg_pace_sec_per_km: int


@dataclass(frozen=True, slots=True)
class PaceEstimate:
    activity_id: uuid.UUID
    started_at: datetime
    source_distance_m: int
    source_pace_sec_per_km: int
    estimated_duration_sec: int


@dataclass(frozen=True, slots=True)
class DistanceResult:
    distance: StandardDistance
    actual: ResultCandidate | None
    estimate: PaceEstimate | None


@dataclass(frozen=True, slots=True)
class PersonalRecords:
    results: tuple[DistanceResult, ...]

    @property
    def best_5k(self) -> ResultCandidate | None:
        return self._actual(StandardDistance.FIVE_K)

    @property
    def best_10k(self) -> ResultCandidate | None:
        return self._actual(StandardDistance.TEN_K)

    def _actual(self, distance: StandardDistance) -> ResultCandidate | None:
        return next(item.actual for item in self.results if item.distance == distance)


@dataclass(frozen=True, slots=True)
class ProgressTotals:
    distance_m: int = 0
    run_count: int = 0
    longest_run_m: int = 0
    elapsed_time_sec: int = 0

    @property
    def average_pace_sec_per_km(self) -> int | None:
        if self.distance_m <= 0:
            return None
        return round(self.elapsed_time_sec * 1000 / self.distance_m)


@dataclass(frozen=True, slots=True)
class WeeklyProgress:
    starts_on: date
    ends_on: date
    totals: ProgressTotals


@dataclass(frozen=True, slots=True)
class PersonalProgress:
    all_time: ProgressTotals
    current_28_days: ProgressTotals
    previous_28_days: ProgressTotals
    weeks: tuple[WeeklyProgress, ...]
    usual_weekly_distance_m: int

    @property
    def current_week(self) -> WeeklyProgress:
        return self.weeks[-1]

    # Keep the established service attributes while /stats moves to the richer DTO.
    @property
    def distance_m(self) -> int:
        return self.all_time.distance_m

    @property
    def run_count(self) -> int:
        return self.all_time.run_count

    @property
    def longest_run_m(self) -> int:
        return self.all_time.longest_run_m


@dataclass(frozen=True, slots=True)
class ProgressBounds:
    as_of: datetime
    current_28_start: datetime
    previous_28_start: datetime
    week_bounds: tuple[tuple[datetime, datetime, date, date], ...]


def progress_bounds(as_of: datetime, timezone_name: str) -> ProgressBounds:
    zone = ZoneInfo(timezone_name)
    aware_as_of = as_of if as_of.tzinfo is not None else as_of.replace(tzinfo=UTC)
    local = aware_as_of.astimezone(zone)
    today_start = datetime.combine(local.date(), time.min, zone)
    current_28_start = today_start - timedelta(days=27)
    previous_28_start = current_28_start - timedelta(days=28)
    current_week_start = today_start - timedelta(days=local.weekday())
    weeks: list[tuple[datetime, datetime, date, date]] = []
    for weeks_ago in range(7, -1, -1):
        start = current_week_start - timedelta(weeks=weeks_ago)
        end = start + timedelta(days=7)
        weeks.append((start.astimezone(UTC), end.astimezone(UTC), start.date(), end.date()))
    return ProgressBounds(
        as_of=aware_as_of.astimezone(UTC),
        current_28_start=current_28_start.astimezone(UTC),
        previous_28_start=previous_28_start.astimezone(UTC),
        week_bounds=tuple(weeks),
    )


def select_personal_records(candidates: tuple[ResultCandidate, ...]) -> PersonalRecords:
    results: list[DistanceResult] = []
    for distance in STANDARD_DISTANCES:
        target = int(distance)
        actual_candidates = tuple(
            item for item in candidates if is_actual_distance(item.distance_m, distance)
        )
        actual = min(
            actual_candidates,
            key=lambda item: (
                item.elapsed_time_sec,
                abs(item.distance_m - target),
                item.activity_id.hex,
            ),
            default=None,
        )
        estimate_candidates = tuple(item for item in candidates if item.distance_m >= target)
        estimate_source = min(
            estimate_candidates,
            key=lambda item: (
                item.avg_pace_sec_per_km * target,
                item.distance_m,
                item.activity_id.hex,
            ),
            default=None,
        )
        estimate = (
            None
            if estimate_source is None
            else PaceEstimate(
                activity_id=estimate_source.activity_id,
                started_at=estimate_source.started_at,
                source_distance_m=estimate_source.distance_m,
                source_pace_sec_per_km=estimate_source.avg_pace_sec_per_km,
                estimated_duration_sec=round(estimate_source.avg_pace_sec_per_km * target / 1000),
            )
        )
        results.append(DistanceResult(distance=distance, actual=actual, estimate=estimate))
    return PersonalRecords(tuple(results))
