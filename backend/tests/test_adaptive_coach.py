import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.activities.domain import SourceType
from app.coach.candidates import RecommendedRunKind, RunDecision
from app.coach.config import DEFAULT_CONFIG
from app.coach.engine import calculate_adaptive_recommendation
from app.coach.facts import (
    HistoricalRunKind,
    RunFact,
    calculate_training_features,
    classify_run,
)
from app.goals.domain import RunningGoalType
from app.readiness.schemas import ReadinessValues

NOW = datetime(2026, 7, 12, 12, tzinfo=UTC)


def run(
    index: int,
    days_ago: int,
    *,
    distance_m: int = 5_000,
    duration_sec: int = 1_800,
    pace: int = 360,
    hr: int | None = 145,
    rpe: int | None = 3,
    title: str | None = "easy",
    elevation: int | None = 20,
) -> RunFact:
    return RunFact(
        uuid.UUID(int=index + 1),
        NOW - timedelta(days=days_ago, seconds=duration_sec),
        distance_m,
        duration_sec,
        duration_sec - 30,
        pace,
        hr,
        None if hr is None else hr + 20,
        170,
        elevation,
        SourceType.MANUAL,
        title,
        rpe,
        True,
    )


def ready(
    *,
    readiness: int = 4,
    fatigue: int = 2,
    soreness: int = 2,
    external_load: int = 2,
    pain: bool = False,
    pain_severity: int | None = None,
    affects_movement: bool | None = None,
    new: bool | None = None,
    worsening: bool | None = None,
    illness: bool = False,
    available_time_sec: int | None = None,
    sleep_quality: int | None = None,
) -> ReadinessValues:
    return ReadinessValues(
        overall_readiness=readiness,
        general_fatigue=fatigue,
        muscle_soreness=soreness,
        sleep_quality=sleep_quality,
        external_load=external_load,
        pain_present=pain,
        pain_severity=pain_severity,
        pain_location="колено" if pain else None,
        pain_affects_movement=affects_movement,
        pain_is_new=new,
        pain_is_worsening=worsening,
        illness_symptoms=illness,
        available_time_sec=available_time_sec,
    )


def regular_history() -> tuple[RunFact, ...]:
    return tuple(
        run(
            index,
            3 + index * 4,
            distance_m=5_000 + index % 3 * 500,
            duration_sec=1_800 + index % 3 * 180,
            pace=355 + index % 4 * 5,
            hr=142 + index % 3,
        )
        for index in range(12)
    )


def test_identical_inputs_and_persistence_order_are_deterministic() -> None:
    history = regular_history()
    first = calculate_adaptive_recommendation(
        history,
        RunningGoalType.FIRST_10K,
        ready(),
        as_of=NOW,
        timezone="Europe/Moscow",
    )
    repeated = calculate_adaptive_recommendation(
        tuple(reversed(history)),
        RunningGoalType.FIRST_10K,
        ready(),
        as_of=NOW,
        timezone="Europe/Moscow",
    )

    assert first.inputs_fingerprint == repeated.inputs_fingerprint
    assert first.rule_result_json() == repeated.rule_result_json()
    assert first.calculator_version == "adaptive-features-v1"
    assert first.rule_version == "adaptive-next-v1"


def test_sparse_history_and_missing_sleep_stay_conservative_without_penalty() -> None:
    result = calculate_adaptive_recommendation(
        (),
        RunningGoalType.GENERAL_ENDURANCE,
        ready(),
        as_of=NOW,
        timezone="UTC",
    )

    assert result.prescription.decision == RunDecision.RUN
    assert result.prescription.kind in {
        RecommendedRunKind.RECOVERY,
        RecommendedRunKind.EASY,
    }
    assert result.prescription.duration_sec is not None
    assert result.prescription.duration_sec % 300 == 0
    assert result.prescription.distance_m is None
    assert result.quality.sleep == 0
    assert result.quality.readiness == 1


@pytest.mark.parametrize(
    "values,code",
    [
        (ready(illness=True), "ILLNESS_REST"),
        (
            ready(
                pain=True,
                pain_severity=4,
                affects_movement=True,
                new=True,
                worsening=False,
            ),
            "PAIN_REST",
        ),
        (
            ready(
                pain=True,
                pain_severity=6,
                affects_movement=False,
                new=False,
                worsening=False,
            ),
            "PAIN_REST",
        ),
    ],
)
def test_hard_safety_returns_rest(values: ReadinessValues, code: str) -> None:
    result = calculate_adaptive_recommendation(
        regular_history(),
        RunningGoalType.IMPROVE_HALF,
        values,
        as_of=NOW,
        timezone="UTC",
    )
    assert result.prescription.decision == RunDecision.REST
    assert code in result.prescription.reason_codes


def test_moderate_pain_and_short_available_time_never_raise_intensity() -> None:
    moderate = calculate_adaptive_recommendation(
        regular_history(),
        RunningGoalType.IMPROVE_MARATHON,
        ready(
            pain=True,
            pain_severity=3,
            affects_movement=False,
            new=True,
            worsening=False,
        ),
        as_of=NOW,
        timezone="UTC",
    )
    too_short = calculate_adaptive_recommendation(
        regular_history(),
        RunningGoalType.FIRST_5K,
        ready(available_time_sec=600),
        as_of=NOW,
        timezone="UTC",
    )
    assert moderate.prescription.kind in {
        RecommendedRunKind.RECOVERY,
        RecommendedRunKind.EASY,
    }
    assert too_short.prescription.decision == RunDecision.REST


def test_six_month_break_does_not_restore_historical_peak_cap() -> None:
    old_history = tuple(
        run(index, 180 + index * 3, distance_m=15_000, duration_sec=5_400) for index in range(20)
    )
    result = calculate_adaptive_recommendation(
        old_history,
        RunningGoalType.FIRST_MARATHON,
        ready(),
        as_of=NOW,
        timezone="UTC",
    )

    assert result.features.historical_longest_m == 15_000
    assert result.features.break_days >= 179
    assert result.prescription.kind in {
        RecommendedRunKind.RECOVERY,
        RecommendedRunKind.EASY,
    }
    assert result.prescription.duration_sec is not None
    assert result.prescription.duration_sec <= DEFAULT_CONFIG.return_duration_cap_sec


def test_hard_classification_requires_two_metrics_without_title_or_rpe() -> None:
    candidate = run(90, 2, pace=320, hr=145, rpe=None, title=None)
    one_signal = classify_run(
        candidate,
        pace_median=360,
        hr_median=145,
        recent_longest_m=6_000,
        config=DEFAULT_CONFIG,
    )
    two_signals = classify_run(
        run(91, 2, pace=320, hr=165, rpe=None, title=None),
        pace_median=360,
        hr_median=145,
        recent_longest_m=6_000,
        config=DEFAULT_CONFIG,
    )
    assert one_signal.kind != HistoricalRunKind.TEMPO
    assert two_signals.kind == HistoricalRunKind.TEMPO


def test_future_incomplete_run_is_excluded_and_recency_uses_end_time() -> None:
    future = RunFact(
        uuid.UUID(int=999),
        NOW - timedelta(minutes=10),
        42_195,
        7_200,
        None,
        180,
        None,
        None,
        None,
        None,
        SourceType.MANUAL,
        "race",
        10,
        True,
    )
    features = calculate_training_features((run(1, 2), future), as_of=NOW, config=DEFAULT_CONFIG)
    assert features.run_count == 1
    assert features.historical_longest_m == 5_000


def test_rounded_short_alternative_never_exceeds_main() -> None:
    result = calculate_adaptive_recommendation(
        regular_history(),
        RunningGoalType.FIRST_HALF,
        ready(sleep_quality=4),
        as_of=NOW,
        timezone="Europe/Moscow",
    )
    prescription = result.prescription
    assert prescription.decision == RunDecision.RUN
    assert prescription.duration_sec is not None
    assert prescription.duration_sec % 300 == 0
    if prescription.distance_m is not None:
        assert prescription.distance_m % 500 == 0
    if prescription.short is not None:
        assert prescription.short.duration_sec < prescription.duration_sec
        if prescription.distance_m is not None and prescription.short.distance_m is not None:
            assert prescription.short.distance_m <= prescription.distance_m
