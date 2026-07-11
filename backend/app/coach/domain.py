from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

CALCULATOR_VERSION = "coach-facts-v2"
RULE_VERSION = "coach-rules-v2"


class RunClassification(StrEnum):
    EASY = "EASY"
    STEADY = "STEADY"
    TEMPO = "TEMPO"
    INTERVAL = "INTERVAL"
    LONG_RUN = "LONG_RUN"
    RECOVERY = "RECOVERY"
    RACE = "RACE"
    UNKNOWN = "UNKNOWN"


class RiskFlag(StrEnum):
    VOLUME_SPIKE = "VOLUME_SPIKE"
    LONG_RUN_SPIKE = "LONG_RUN_SPIKE"
    EXCESSIVE_HARD_RUNS = "EXCESSIVE_HARD_RUNS"
    INSUFFICIENT_REST = "INSUFFICIENT_REST"
    MISSING_HISTORY = "MISSING_HISTORY"
    LOW_QUALITY_DATA = "LOW_QUALITY_DATA"


@dataclass(frozen=True, slots=True)
class RunFact:
    started_at: datetime
    distance_m: int
    elapsed_time_sec: int
    avg_pace_sec_per_km: int
    title: str | None = None


@dataclass(frozen=True, slots=True)
class WindowFacts:
    distance_m: int
    run_count: int
    longest_run_m: int


@dataclass(frozen=True, slots=True)
class CoachFacts:
    calculator_version: str
    rule_version: str
    week: WindowFacts
    month: WindowFacts
    last_7d: WindowFacts
    last_30d: WindowFacts
    all_time_longest_m: int
    average_pace_30d: int | None
    baseline_weekly_distance_m: int
    previous_weeks: tuple[WindowFacts, WindowFacts]
    recent_history_run_count: int
    last_completed_local_date: date | None
    classification_counts_30d: dict[str, int]
    risk_flags: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "calculator_version": self.calculator_version,
            "rule_version": self.rule_version,
            "week": asdict(self.week),
            "month": asdict(self.month),
            "last_7d": asdict(self.last_7d),
            "last_30d": asdict(self.last_30d),
            "all_time_longest_m": self.all_time_longest_m,
            "average_pace_30d": self.average_pace_30d,
            "baseline_weekly_distance_m": self.baseline_weekly_distance_m,
            "previous_weeks": [asdict(item) for item in self.previous_weeks],
            "recent_history_run_count": self.recent_history_run_count,
            "last_completed_local_date": (
                self.last_completed_local_date.isoformat()
                if self.last_completed_local_date is not None
                else None
            ),
            "classification_counts_30d": dict(self.classification_counts_30d),
            "risk_flags": list(self.risk_flags),
        }


@dataclass(frozen=True, slots=True)
class WorkoutRecommendation:
    recommended_on: date
    workout_type: RunClassification
    distance_m: int
    duration_sec: int
    pace_min_sec_per_km: int | None
    pace_max_sec_per_km: int | None
    reason: str
    risk_flags: tuple[str, ...]
    observations: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "rule_version": RULE_VERSION,
            "recommended_on": self.recommended_on.isoformat(),
            "workout_type": self.workout_type.value,
            "distance_m": self.distance_m,
            "duration_sec": self.duration_sec,
            "pace_min_sec_per_km": self.pace_min_sec_per_km,
            "pace_max_sec_per_km": self.pace_max_sec_per_km,
            "reason": self.reason,
            "risk_flags": list(self.risk_flags),
            "observations": list(self.observations),
        }


def calendar_bounds(moment: datetime, timezone: str, *, month: bool) -> tuple[datetime, datetime]:
    zone = ZoneInfo(timezone)
    local = moment.astimezone(zone)
    if month:
        start_date = local.date().replace(day=1)
        next_month = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
        end_date = next_month
    else:
        start_date = local.date() - timedelta(days=local.weekday())
        end_date = start_date + timedelta(days=7)
    return (
        datetime.combine(start_date, time.min, zone).astimezone(UTC),
        datetime.combine(end_date, time.min, zone).astimezone(UTC),
    )


def classify_run(
    run: RunFact, *, baseline_pace_sec_per_km: int | None, baseline_long_run_m: int
) -> RunClassification:
    title = (run.title or "").casefold()
    keywords = (
        (("race", "забег", "соревн"), RunClassification.RACE),
        (("interval", "интервал"), RunClassification.INTERVAL),
        (("tempo", "темп"), RunClassification.TEMPO),
        (("recovery", "восстанов"), RunClassification.RECOVERY),
        (("easy", "легк"), RunClassification.EASY),
        (("long", "длинн"), RunClassification.LONG_RUN),
    )
    for variants, classification in keywords:
        if any(value in title for value in variants):
            return classification
    if (
        run.distance_m <= 0
        or run.elapsed_time_sec <= 0
        or not 120 <= run.avg_pace_sec_per_km <= 1_800
    ):
        return RunClassification.UNKNOWN
    if baseline_long_run_m >= 5_000 and run.distance_m >= max(10_000, baseline_long_run_m * 3 // 2):
        return RunClassification.LONG_RUN
    if baseline_pace_sec_per_km is None:
        return RunClassification.STEADY
    ratio = run.avg_pace_sec_per_km / baseline_pace_sec_per_km
    if ratio >= 1.15:
        return RunClassification.RECOVERY
    if ratio >= 1.05:
        return RunClassification.EASY
    if ratio <= 0.90:
        return RunClassification.TEMPO
    return RunClassification.STEADY


def calculate_facts(runs: tuple[RunFact, ...], *, as_of: datetime, timezone: str) -> CoachFacts:
    aware_as_of = as_of if as_of.tzinfo is not None else as_of.replace(tzinfo=UTC)
    ordered = tuple(
        sorted(
            (
                run
                for run in runs
                if run.started_at + timedelta(seconds=run.elapsed_time_sec) <= aware_as_of
            ),
            key=lambda item: item.started_at,
        )
    )
    week_start, week_end = calendar_bounds(aware_as_of, timezone, month=False)
    month_start, month_end = calendar_bounds(aware_as_of, timezone, month=True)
    zone = ZoneInfo(timezone)
    seven_start = aware_as_of - timedelta(days=7)
    thirty_start = aware_as_of - timedelta(days=30)
    current_7 = tuple(run for run in ordered if seven_start <= run.started_at <= aware_as_of)
    current_30 = tuple(run for run in ordered if thirty_start <= run.started_at <= aware_as_of)
    prior_week = _window(ordered, week_start - timedelta(weeks=1), week_start)
    earlier_week = _window(
        ordered, week_start - timedelta(weeks=2), week_start - timedelta(weeks=1)
    )
    previous_weeks = (earlier_week, prior_week)
    recent_history_run_count = (
        sum(item.run_count for item in previous_weeks)
        + _window(ordered, week_start, week_end).run_count
    )
    baseline_weekly = sum(item.distance_m for item in previous_weeks) // 2
    recent_baseline_runs = tuple(
        run for run in ordered if week_start - timedelta(weeks=2) <= run.started_at < week_start
    )
    baseline_pace = _weighted_pace(recent_baseline_runs or current_30)
    baseline_long = max((run.distance_m for run in recent_baseline_runs), default=0)
    classifications = tuple(
        classify_run(
            run,
            baseline_pace_sec_per_km=baseline_pace,
            baseline_long_run_m=baseline_long,
        )
        for run in current_30
    )
    flags: list[RiskFlag] = []
    current_week = _window(ordered, week_start, week_end)
    if baseline_weekly > 0 and current_week.distance_m * 100 >= baseline_weekly * 130:
        flags.append(RiskFlag.VOLUME_SPIKE)
    current_long = max((run.distance_m for run in current_7), default=0)
    if baseline_long > 0 and current_long * 100 >= baseline_long * 125:
        flags.append(RiskFlag.LONG_RUN_SPIKE)
    hard = sum(
        classification
        in {RunClassification.TEMPO, RunClassification.INTERVAL, RunClassification.RACE}
        for run, classification in zip(current_30, classifications, strict=True)
        if run in current_7
    )
    if hard >= 3:
        flags.append(RiskFlag.EXCESSIVE_HARD_RUNS)
    if _has_no_rest(current_7, aware_as_of, timezone):
        flags.append(RiskFlag.INSUFFICIENT_REST)
    if recent_history_run_count < 3:
        flags.append(RiskFlag.MISSING_HISTORY)
    if any(not 120 <= run.avg_pace_sec_per_km <= 1_800 for run in ordered):
        flags.append(RiskFlag.LOW_QUALITY_DATA)
    counts = Counter(classification.value for classification in classifications)
    return CoachFacts(
        calculator_version=CALCULATOR_VERSION,
        rule_version=RULE_VERSION,
        week=_window(ordered, week_start, week_end),
        month=_window(ordered, month_start, month_end),
        last_7d=_window(current_7),
        last_30d=_window(current_30),
        all_time_longest_m=max((run.distance_m for run in ordered), default=0),
        average_pace_30d=_weighted_pace(current_30),
        baseline_weekly_distance_m=baseline_weekly,
        previous_weeks=previous_weeks,
        recent_history_run_count=recent_history_run_count,
        last_completed_local_date=(
            ordered[-1].started_at.astimezone(zone).date() if ordered else None
        ),
        classification_counts_30d=dict(sorted(counts.items())),
        risk_flags=tuple(flag.value for flag in flags),
    )


def recommend_next(facts: CoachFacts, *, as_of: datetime, timezone: str) -> WorkoutRecommendation:
    pace = facts.average_pace_30d
    risk_flags = facts.risk_flags
    local_today = as_of.astimezone(ZoneInfo(timezone)).date()
    last_date = facts.last_completed_local_date or local_today
    observations = _observations(risk_flags)
    if RiskFlag.MISSING_HISTORY.value in risk_flags:
        return WorkoutRecommendation(
            max(local_today, last_date + timedelta(days=1)),
            RunClassification.EASY,
            3_000,
            1_800,
            None if pace is None else pace + 20,
            None if pace is None else pace + 60,
            "Недавней истории пока мало, поэтому начинаем с короткой спокойной пробежки.",
            risk_flags,
            observations,
        )
    if any(
        flag in risk_flags
        for flag in (
            RiskFlag.VOLUME_SPIKE.value,
            RiskFlag.LONG_RUN_SPIKE.value,
            RiskFlag.EXCESSIVE_HARD_RUNS.value,
            RiskFlag.INSUFFICIENT_REST.value,
        )
    ):
        distance = max(3_000, min(6_000, facts.baseline_weekly_distance_m // 5))
        distance = min(distance, max(3_000, facts.all_time_longest_m))
        return WorkoutRecommendation(
            max(local_today, last_date + timedelta(days=2)),
            RunClassification.RECOVERY,
            distance,
            _duration(distance, pace, 60),
            None if pace is None else pace + 30,
            None if pace is None else pace + 75,
            "Недавняя нагрузка выше обычной, поэтому следующую тренировку "
            "лучше сделать восстановительной.",
            risk_flags,
            observations,
        )
    distance = max(4_000, min(10_000, facts.baseline_weekly_distance_m // 4))
    distance = min(distance, max(3_000, facts.all_time_longest_m))
    return WorkoutRecommendation(
        max(local_today, last_date + timedelta(days=1)),
        RunClassification.EASY,
        distance,
        _duration(distance, pace, 35),
        None if pace is None else pace + 15,
        None if pace is None else pace + 50,
        "Спокойная пробежка сохраняет привычный недельный объём без резкого повышения.",
        risk_flags,
        observations,
    )


def _observations(risk_flags: tuple[str, ...]) -> tuple[str, ...]:
    labels = {
        RiskFlag.VOLUME_SPIKE.value: "за текущую неделю объём заметно выше обычного",
        RiskFlag.LONG_RUN_SPIKE.value: "самая длинная недавняя пробежка заметно длиннее привычной",
        RiskFlag.EXCESSIVE_HARD_RUNS.value: "за последние 7 дней было много интенсивных тренировок",
        RiskFlag.INSUFFICIENT_REST.value: "семь дней подряд были пробежки",
        RiskFlag.MISSING_HISTORY.value: "за текущую и две предыдущие недели мало данных",
        RiskFlag.LOW_QUALITY_DATA.value: "у части тренировок недостаточно надёжных данных о темпе",
    }
    return tuple(labels[flag] for flag in risk_flags if flag in labels)


def safe_weekly_targets(baseline_m: int, weeks: int = 4) -> tuple[int, ...]:
    start = max(9_000, baseline_m)
    targets: list[int] = []
    current = start
    for _ in range(weeks):
        current = current if not targets else current * 110 // 100
        targets.append(current)
    return tuple(targets)


def _window(
    runs: tuple[RunFact, ...], start: datetime | None = None, end: datetime | None = None
) -> WindowFacts:
    if start is None:
        selected = runs
    else:
        assert end is not None
        selected = tuple(run for run in runs if start <= run.started_at < end)
    return WindowFacts(
        sum(run.distance_m for run in selected),
        len(selected),
        max((run.distance_m for run in selected), default=0),
    )


def _weighted_pace(runs: tuple[RunFact, ...]) -> int | None:
    distance = sum(run.distance_m for run in runs if run.distance_m > 0)
    if distance == 0:
        return None
    return round(sum(run.elapsed_time_sec for run in runs if run.distance_m > 0) * 1000 / distance)


def _duration(distance_m: int, pace: int | None, pace_addition: int) -> int:
    return max(1_200, distance_m * ((pace or 360) + pace_addition) // 1000)


def _has_no_rest(runs: tuple[RunFact, ...], as_of: datetime, timezone: str) -> bool:
    zone = ZoneInfo(timezone)
    days = {run.started_at.astimezone(zone).date() for run in runs}
    today: date = as_of.astimezone(zone).date()
    return all(today - timedelta(days=offset) in days for offset in range(7))
