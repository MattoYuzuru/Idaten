from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from app.coach.facts import RunFact, TrainingFeatures
from app.readiness.schemas import ReadinessValues


@dataclass(frozen=True, slots=True)
class DataQualityAssessment:
    overall: float
    volume: float
    pace: float
    heart_rate: float
    readiness: float
    sleep: float
    missing_categories: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return asdict(self)


def assess_data_quality(
    runs: tuple[RunFact, ...],
    features: TrainingFeatures,
    readiness: ReadinessValues,
    *,
    as_of: datetime,
) -> DataQualityAssessment:
    complete = tuple(run for run in runs if run.ended_at <= as_of)
    volume = min(1.0, features.run_count / 8)
    plausible_paces = sum(120 <= run.avg_pace_sec_per_km <= 1_800 for run in complete)
    pace = min(1.0, plausible_paces / 6) * (plausible_paces / max(1, len(complete)))
    plausible_hr = sum(run.avg_hr is not None and 40 <= run.avg_hr <= 240 for run in complete)
    heart_rate = min(1.0, plausible_hr / 6) * (plausible_hr / max(1, len(complete)))
    readiness_score = 1.0
    sleep_present = readiness.sleep_quality is not None or readiness.sleep_duration_sec is not None
    sleep = 0.0
    if sleep_present:
        sleep = 1.0
        if readiness.sleep_ended_at is not None:
            now = as_of if as_of.tzinfo else as_of.replace(tzinfo=UTC)
            ended = (
                readiness.sleep_ended_at
                if readiness.sleep_ended_at.tzinfo
                else readiness.sleep_ended_at.replace(tzinfo=UTC)
            )
            if now - ended > timedelta(hours=36):
                sleep = 0.0
    weighted = [(volume, 0.35), (pace, 0.20), (readiness_score, 0.25)]
    if heart_rate > 0:
        weighted.append((heart_rate, 0.10))
    if sleep_present and sleep > 0:
        weighted.append((sleep, 0.10))
    total_weight = sum(weight for _value, weight in weighted)
    overall = sum(value * weight for value, weight in weighted) / total_weight
    missing: list[str] = []
    if volume < 0.5:
        missing.append("история объёма")
    if pace < 0.5:
        missing.append("надёжный темп")
    if heart_rate == 0:
        missing.append("пульс")
    if not sleep_present:
        missing.append("сон")
    return DataQualityAssessment(
        round(overall, 4),
        round(volume, 4),
        round(pace, 4),
        round(heart_rate, 4),
        readiness_score,
        sleep,
        tuple(missing),
    )
