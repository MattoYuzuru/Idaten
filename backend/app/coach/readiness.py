from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta

from app.readiness.schemas import ReadinessValues


@dataclass(frozen=True, slots=True)
class AthleteState:
    readiness_score: float
    hard_rest: bool
    moderate_pain: bool
    high_external_load: bool
    reason_codes: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return asdict(self)


def assess_readiness(values: ReadinessValues) -> AthleteState:
    if values.overall_readiness is None:
        raise ValueError("overall_readiness is required")
    if values.general_fatigue is None or values.muscle_soreness is None:
        raise ValueError("fatigue and soreness are required")
    if values.external_load is None or values.illness_symptoms is None:
        raise ValueError("external load and illness are required")
    positive: list[tuple[float, float]] = [((values.overall_readiness - 1) / 4, 0.65)]
    if values.motivation is not None:
        positive.append(((values.motivation - 1) / 4, 0.15))
    sleep_signals: list[float] = []
    if values.sleep_quality is not None:
        sleep_signals.append((values.sleep_quality - 1) / 4)
    if values.sleep_duration_sec is not None:
        sleep_signals.append(min(1.0, max(0.0, values.sleep_duration_sec / 28_800)))
    if sleep_signals:
        positive.append((sum(sleep_signals) / len(sleep_signals), 0.20))
    positive_score = sum(value * weight for value, weight in positive) / sum(
        weight for _value, weight in positive
    )
    load = (
        0.45 * values.general_fatigue / 10
        + 0.35 * values.muscle_soreness / 10
        + 0.20 * values.external_load / 10
    )
    score = min(1.0, max(0.0, 0.70 * positive_score + 0.30 * (1 - load)))
    severe_pain = values.pain_present is True and (
        (values.pain_severity or 0) >= 6
        or values.pain_affects_movement is True
        or values.pain_is_worsening is True
    )
    moderate_pain = values.pain_present is True and not severe_pain
    reasons: list[str] = []
    if values.illness_symptoms:
        reasons.append("ILLNESS_REST")
    if severe_pain:
        reasons.append("PAIN_REST")
    if moderate_pain:
        reasons.append("PAIN_CAUTION")
    if score < 0.25:
        reasons.append("VERY_LOW_READINESS")
    elif score < 0.45:
        reasons.append("LOW_READINESS")
    if values.external_load >= 8:
        reasons.append("HIGH_EXTERNAL_LOAD")
    return AthleteState(
        round(score, 4),
        bool(values.illness_symptoms or severe_pain or score < 0.25),
        moderate_pain,
        values.external_load >= 8,
        tuple(reasons),
    )


def without_stale_sleep(values: ReadinessValues, *, as_of: datetime) -> ReadinessValues:
    if values.sleep_ended_at is None:
        return values
    now = as_of if as_of.tzinfo is not None else as_of.replace(tzinfo=UTC)
    ended = (
        values.sleep_ended_at
        if values.sleep_ended_at.tzinfo is not None
        else values.sleep_ended_at.replace(tzinfo=UTC)
    )
    age = now.astimezone(UTC) - ended.astimezone(UTC)
    if timedelta(0) <= age <= timedelta(hours=36):
        return values
    return replace(
        values,
        sleep_quality=None,
        sleep_duration_sec=None,
        sleep_ended_at=None,
        sleep_summary_id=None,
    )
