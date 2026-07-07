from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest

from app.coach.domain import (
    CALCULATOR_VERSION,
    RULE_VERSION,
    RiskFlag,
    RunClassification,
    RunFact,
    calculate_facts,
    calendar_bounds,
    classify_run,
    recommend_next,
    safe_weekly_targets,
)

NOW = datetime(2026, 7, 8, 12, tzinfo=UTC)


def run(
    days_ago: int,
    distance_m: int = 5_000,
    pace: int = 360,
    title: str | None = None,
) -> RunFact:
    return RunFact(
        NOW - timedelta(days=days_ago),
        distance_m,
        distance_m * pace // 1000,
        pace,
        title,
    )


@pytest.mark.parametrize(
    ("pace", "expected"),
    [
        (414, RunClassification.RECOVERY),
        (378, RunClassification.EASY),
        (377, RunClassification.STEADY),
        (325, RunClassification.STEADY),
        (324, RunClassification.TEMPO),
    ],
)
def test_run_classification_pace_boundaries(pace: int, expected: RunClassification) -> None:
    assert (
        classify_run(run(0, pace=pace), baseline_pace_sec_per_km=360, baseline_long_run_m=10_000)
        == expected
    )


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        (run(0, title="6 x interval"), RunClassification.INTERVAL),
        (run(0, title="City race"), RunClassification.RACE),
        (run(0, 15_000), RunClassification.LONG_RUN),
        (run(0, pace=1_801), RunClassification.UNKNOWN),
    ],
)
def test_run_classification_semantic_and_quality_boundaries(
    sample: RunFact, expected: RunClassification
) -> None:
    assert (
        classify_run(sample, baseline_pace_sec_per_km=360, baseline_long_run_m=10_000) == expected
    )


def test_week_month_boundaries_respect_timezone() -> None:
    moment = datetime(2026, 7, 5, 21, 30, tzinfo=UTC)  # Monday 00:30 in Moscow.
    week_start, week_end = calendar_bounds(moment, "Europe/Moscow", month=False)
    month_start, month_end = calendar_bounds(moment, "Europe/Moscow", month=True)

    assert week_start == datetime(2026, 7, 5, 21, tzinfo=UTC)
    assert week_end == datetime(2026, 7, 12, 21, tzinfo=UTC)
    assert month_start == datetime(2026, 6, 30, 21, tzinfo=UTC)
    assert month_end == datetime(2026, 7, 31, 21, tzinfo=UTC)


def test_facts_and_recommendation_are_deterministic_and_versioned() -> None:
    samples = (run(1), run(8), run(15), run(22))
    first = calculate_facts(samples, as_of=NOW, timezone="UTC")
    second = calculate_facts(tuple(reversed(samples)), as_of=NOW, timezone="UTC")

    assert first == second
    assert first.as_json() == second.as_json()
    assert recommend_next(first) == recommend_next(second)
    assert first.calculator_version == CALCULATOR_VERSION
    assert first.rule_version == RULE_VERSION
    assert first.average_pace_30d == 360


def test_volume_and_long_run_spike_exact_boundaries() -> None:
    samples = (
        run(0, 13_000),
        run(8, 7_500),
        run(15, 7_500),
        run(22, 7_500),
        run(29, 7_500),
        run(35, 10_000),
    )
    facts = calculate_facts(samples, as_of=NOW, timezone="UTC")

    assert facts.baseline_weekly_distance_m == 10_000
    assert RiskFlag.VOLUME_SPIKE.value in facts.risk_flags
    assert RiskFlag.LONG_RUN_SPIKE.value in facts.risk_flags


def test_excessive_hard_runs_and_no_rest_boundaries() -> None:
    samples = tuple(run(day, title="tempo") for day in range(7))
    facts = calculate_facts(samples, as_of=NOW, timezone="UTC")

    assert RiskFlag.EXCESSIVE_HARD_RUNS.value in facts.risk_flags
    assert RiskFlag.INSUFFICIENT_REST.value in facts.risk_flags


def test_missing_and_low_quality_data_flags() -> None:
    facts = calculate_facts((run(0, pace=1_801),), as_of=NOW, timezone="UTC")

    assert facts.risk_flags == (
        RiskFlag.MISSING_HISTORY.value,
        RiskFlag.LOW_QUALITY_DATA.value,
    )
    assert recommend_next(facts).workout_type == RunClassification.EASY


def test_plan_targets_never_grow_more_than_ten_percent() -> None:
    targets = safe_weekly_targets(20_000)

    assert targets[0] == 20_000
    assert all(current * 100 <= previous * 110 for previous, current in pairwise(targets))
