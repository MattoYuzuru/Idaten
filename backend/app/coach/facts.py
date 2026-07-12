from __future__ import annotations

import math
import statistics
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from itertools import pairwise

from app.activities.domain import SourceType
from app.coach.config import AdaptiveCoachConfig


class HistoricalRunKind(StrEnum):
    RECOVERY = "RECOVERY"
    EASY = "EASY"
    STEADY = "STEADY"
    TEMPO = "TEMPO"
    INTERVAL = "INTERVAL"
    LONG_RUN = "LONG_RUN"
    RACE = "RACE"
    UNKNOWN = "UNKNOWN"

    @property
    def hard(self) -> bool:
        return self in {self.TEMPO, self.INTERVAL, self.RACE}


@dataclass(frozen=True, slots=True)
class RunFact:
    activity_id: uuid.UUID
    started_at: datetime
    distance_m: int
    elapsed_time_sec: int
    moving_time_sec: int | None
    avg_pace_sec_per_km: int
    avg_hr: int | None
    max_hr: int | None
    avg_cadence_spm: int | None
    elevation_gain_m: int | None
    source_type: SourceType
    title: str | None
    session_rpe: int | None
    start_time_known: bool

    @property
    def ended_at(self) -> datetime:
        started = self.started_at if self.started_at.tzinfo else self.started_at.replace(tzinfo=UTC)
        return started + timedelta(seconds=self.elapsed_time_sec)


@dataclass(frozen=True, slots=True)
class RunClassification:
    activity_id: uuid.UUID
    kind: HistoricalRunKind
    confidence: float
    load: float


@dataclass(frozen=True, slots=True)
class WindowFeature:
    days: int
    distance_m: int
    duration_sec: int
    run_count: int
    longest_m: int


@dataclass(frozen=True, slots=True)
class WeightedFeature:
    half_life_days: int
    distance_m: float
    duration_sec: float
    training_load: float


@dataclass(frozen=True, slots=True)
class TrainingFeatures:
    windows: tuple[WindowFeature, ...]
    weighted: tuple[WeightedFeature, ...]
    classifications: tuple[RunClassification, ...]
    run_count: int
    days_since_last_run: float | None
    days_since_hard_run: float | None
    days_since_long_run: float | None
    maximum_gap_days: float
    break_days: float
    peak_7d_distance_m: int
    historical_longest_m: int
    recent_longest_m: int
    hard_density_28d: float
    robust_pace_sec_per_km: int | None
    robust_hr: int | None
    base_duration_sec: int
    experience_confidence: float

    def window(self, days: int) -> WindowFeature:
        return next(item for item in self.windows if item.days == days)

    def as_json(self) -> dict[str, object]:
        return {
            "windows": [asdict(item) for item in self.windows],
            "weighted": [asdict(item) for item in self.weighted],
            "classifications": [
                {
                    "activity_id": str(item.activity_id),
                    "kind": item.kind.value,
                    "confidence": item.confidence,
                    "load": item.load,
                }
                for item in self.classifications
            ],
            "run_count": self.run_count,
            "days_since_last_run": self.days_since_last_run,
            "days_since_hard_run": self.days_since_hard_run,
            "days_since_long_run": self.days_since_long_run,
            "maximum_gap_days": self.maximum_gap_days,
            "break_days": self.break_days,
            "peak_7d_distance_m": self.peak_7d_distance_m,
            "historical_longest_m": self.historical_longest_m,
            "recent_longest_m": self.recent_longest_m,
            "hard_density_28d": self.hard_density_28d,
            "robust_pace_sec_per_km": self.robust_pace_sec_per_km,
            "robust_hr": self.robust_hr,
            "base_duration_sec": self.base_duration_sec,
            "experience_confidence": self.experience_confidence,
        }


def recency_weight(age_days: float, half_life_days: float) -> float:
    return 2 ** (-max(0.0, age_days) / half_life_days)


def calculate_training_features(
    runs: tuple[RunFact, ...], *, as_of: datetime, config: AdaptiveCoachConfig
) -> TrainingFeatures:
    now = as_of if as_of.tzinfo else as_of.replace(tzinfo=UTC)
    ordered = tuple(
        sorted(
            (run for run in runs if run.ended_at <= now),
            key=lambda run: (run.started_at, run.activity_id.hex),
        )
    )
    plausible_paces = tuple(
        run.avg_pace_sec_per_km for run in ordered if 120 <= run.avg_pace_sec_per_km <= 1_800
    )
    plausible_hr = tuple(run.avg_hr for run in ordered if run.avg_hr and 40 <= run.avg_hr <= 240)
    pace_median = _median_int(plausible_paces)
    hr_median = _median_int(plausible_hr)
    longest_recent_reference = max(
        (run.distance_m for run in ordered if run.ended_at >= now - timedelta(days=90)),
        default=0,
    )
    classifications = tuple(
        classify_run(
            run,
            pace_median=pace_median,
            hr_median=hr_median,
            recent_longest_m=longest_recent_reference,
            config=config,
        )
        for run in ordered
    )
    kind_by_id = {item.activity_id: item for item in classifications}
    windows = tuple(_window(ordered, now, days) for days in (7, 28, 42, 90))
    weighted = tuple(
        _weighted(ordered, classifications, now, half_life, config)
        for half_life in (7, 28, 90, 365)
    )
    gaps = tuple(
        max(0.0, (current.started_at - previous.ended_at).total_seconds() / 86_400)
        for previous, current in pairwise(ordered)
    )
    last = ordered[-1] if ordered else None
    last_hard = next(
        (run for run in reversed(ordered) if kind_by_id[run.activity_id].kind.hard), None
    )
    last_long = next(
        (
            run
            for run in reversed(ordered)
            if kind_by_id[run.activity_id].kind == HistoricalRunKind.LONG_RUN
        ),
        None,
    )
    recent_28 = tuple(run for run in ordered if run.ended_at >= now - timedelta(days=28))
    hard_count = sum(kind_by_id[run.activity_id].kind.hard for run in recent_28)
    base_candidates = tuple(
        run.elapsed_time_sec
        for run in ordered
        if run.ended_at >= now - timedelta(days=90)
        and not kind_by_id[run.activity_id].kind.hard
        and 600 <= run.elapsed_time_sec <= 21_600
    )
    return TrainingFeatures(
        windows=windows,
        weighted=weighted,
        classifications=classifications,
        run_count=len(ordered),
        days_since_last_run=_days_since(last, now),
        days_since_hard_run=_days_since(last_hard, now),
        days_since_long_run=_days_since(last_long, now),
        maximum_gap_days=max(gaps, default=0.0),
        break_days=_days_since(last, now) or 0.0,
        peak_7d_distance_m=_peak_distance(ordered, timedelta(days=7)),
        historical_longest_m=max((run.distance_m for run in ordered), default=0),
        recent_longest_m=windows[-1].longest_m,
        hard_density_28d=hard_count / max(1, len(recent_28)),
        robust_pace_sec_per_km=pace_median,
        robust_hr=hr_median,
        base_duration_sec=_median_int(base_candidates) or config.no_history_duration_sec,
        experience_confidence=min(1.0, math.log1p(len(ordered)) / math.log(25)),
    )


def classify_run(
    run: RunFact,
    *,
    pace_median: int | None,
    hr_median: int | None,
    recent_longest_m: int,
    config: AdaptiveCoachConfig,
) -> RunClassification:
    title = (run.title or "").casefold()
    explicit = (
        (("race", "забег", "соревн"), HistoricalRunKind.RACE),
        (("interval", "интервал"), HistoricalRunKind.INTERVAL),
        (("tempo", "темп"), HistoricalRunKind.TEMPO),
        (("recovery", "восстанов"), HistoricalRunKind.RECOVERY),
        (("easy", "легк"), HistoricalRunKind.EASY),
        (("long", "длинн"), HistoricalRunKind.LONG_RUN),
    )
    title_kind = next(
        (kind for words, kind in explicit if any(word in title for word in words)), None
    )
    pace_hard = pace_median is not None and run.avg_pace_sec_per_km <= pace_median * 0.9
    hr_hard = hr_median is not None and run.avg_hr is not None and run.avg_hr >= hr_median * 1.08
    rpe_hard = run.session_rpe is not None and run.session_rpe >= 7
    if title_kind is not None:
        kind, confidence = title_kind, 0.9
    elif rpe_hard:
        kind, confidence = HistoricalRunKind.TEMPO, 0.85
    elif pace_hard and hr_hard:
        kind, confidence = HistoricalRunKind.TEMPO, 0.75
    elif recent_longest_m >= 8_000 and run.distance_m >= max(10_000, recent_longest_m * 5 // 4):
        kind, confidence = HistoricalRunKind.LONG_RUN, 0.7
    elif run.session_rpe is not None and run.session_rpe <= 3:
        kind, confidence = HistoricalRunKind.EASY, 0.8
    elif pace_median is None:
        kind, confidence = HistoricalRunKind.UNKNOWN, 0.35
    elif run.avg_pace_sec_per_km >= pace_median * 1.1:
        kind, confidence = HistoricalRunKind.RECOVERY, 0.6
    else:
        kind, confidence = HistoricalRunKind.STEADY, 0.55
    duration_minutes = run.elapsed_time_sec / 60
    elevation = 1.0
    if run.elevation_gain_m is not None and run.distance_m > 0:
        elevation = min(1.25, 1.0 + run.elevation_gain_m / max(1, run.distance_m) * 2)
    load = (
        duration_minutes
        * (
            float(run.session_rpe)
            if run.session_rpe is not None
            else config.load_factor(kind.value)
        )
        * elevation
    )
    return RunClassification(run.activity_id, kind, confidence, round(load, 3))


def _window(runs: tuple[RunFact, ...], now: datetime, days: int) -> WindowFeature:
    selected = tuple(run for run in runs if run.ended_at >= now - timedelta(days=days))
    return WindowFeature(
        days,
        sum(run.distance_m for run in selected),
        sum(run.elapsed_time_sec for run in selected),
        len(selected),
        max((run.distance_m for run in selected), default=0),
    )


def _weighted(
    runs: tuple[RunFact, ...],
    classifications: tuple[RunClassification, ...],
    now: datetime,
    half_life: int,
    config: AdaptiveCoachConfig,
) -> WeightedFeature:
    by_id = {item.activity_id: item for item in classifications}
    pairs = tuple(
        (run, recency_weight((now - run.ended_at).total_seconds() / 86_400, half_life))
        for run in runs
    )
    return WeightedFeature(
        half_life,
        round(sum(run.distance_m * weight for run, weight in pairs), 3),
        round(sum(run.elapsed_time_sec * weight for run, weight in pairs), 3),
        round(sum(by_id[run.activity_id].load * weight for run, weight in pairs), 3),
    )


def _peak_distance(runs: tuple[RunFact, ...], width: timedelta) -> int:
    peak = 0
    for run in runs:
        end = run.ended_at + width
        peak = max(
            peak, sum(item.distance_m for item in runs if run.ended_at <= item.ended_at < end)
        )
    return peak


def _days_since(run: RunFact | None, now: datetime) -> float | None:
    return None if run is None else max(0.0, (now - run.ended_at).total_seconds() / 86_400)


def _median_int(values: tuple[int, ...]) -> int | None:
    return None if not values else round(statistics.median(values))
