from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.coach.candidates import (
    RecommendedRunKind,
    RunDecision,
    ScoredCandidate,
)
from app.coach.config import AdaptiveCoachConfig
from app.coach.facts import HistoricalRunKind, RunFact, TrainingFeatures
from app.coach.quality import DataQualityAssessment
from app.coach.readiness import AthleteState
from app.goals.domain import RunningGoalType
from app.readiness.schemas import ReadinessValues


@dataclass(frozen=True, slots=True)
class ShortAlternative:
    duration_sec: int
    distance_m: int | None
    kind: RecommendedRunKind


@dataclass(frozen=True, slots=True)
class SafeBounds:
    minimum_duration_sec: int
    maximum_duration_sec: int
    maximum_distance_m: int | None
    maximum_kind: RecommendedRunKind


@dataclass(frozen=True, slots=True)
class Prescription:
    decision: RunDecision
    kind: RecommendedRunKind | None
    recommended_for: date
    not_before: datetime
    valid_until: datetime
    duration_sec: int | None
    distance_m: int | None
    pace_min_sec_per_km: int | None
    pace_max_sec_per_km: int | None
    hr_min: int | None
    hr_max: int | None
    rpe_min: int | None
    rpe_max: int | None
    short: ShortAlternative | None
    safe_bounds: SafeBounds | None
    confidence: float
    reason_codes: tuple[str, ...]
    observations: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        short: dict[str, object] | None = None
        if self.short is not None:
            short = {
                "duration_sec": self.short.duration_sec,
                "distance_m": self.short.distance_m,
                "kind": self.short.kind.value,
            }
        bounds: dict[str, object] | None = None
        if self.safe_bounds is not None:
            bounds = {
                "minimum_duration_sec": self.safe_bounds.minimum_duration_sec,
                "maximum_duration_sec": self.safe_bounds.maximum_duration_sec,
                "maximum_distance_m": self.safe_bounds.maximum_distance_m,
                "maximum_kind": self.safe_bounds.maximum_kind.value,
            }
        return {
            "decision": self.decision.value,
            "kind": None if self.kind is None else self.kind.value,
            "recommended_for": self.recommended_for.isoformat(),
            "not_before": self.not_before.isoformat(),
            "valid_until": self.valid_until.isoformat(),
            "duration_sec": self.duration_sec,
            "distance_m": self.distance_m,
            "pace_min_sec_per_km": self.pace_min_sec_per_km,
            "pace_max_sec_per_km": self.pace_max_sec_per_km,
            "hr_min": self.hr_min,
            "hr_max": self.hr_max,
            "rpe_min": self.rpe_min,
            "rpe_max": self.rpe_max,
            "short": short,
            "safe_bounds": bounds,
            "confidence": self.confidence,
            "reason_codes": list(self.reason_codes),
            "observations": list(self.observations),
        }


def build_prescription(
    selected: ScoredCandidate,
    features: TrainingFeatures,
    state: AthleteState,
    quality: DataQualityAssessment,
    readiness: ReadinessValues,
    goal: RunningGoalType,
    runs: tuple[RunFact, ...],
    *,
    as_of: datetime,
    timezone: str,
    safety_reasons: tuple[str, ...],
    config: AdaptiveCoachConfig,
) -> Prescription:
    now = as_of if as_of.tzinfo else as_of.replace(tzinfo=UTC)
    latest = max(runs, key=lambda run: (run.started_at, run.activity_id.hex), default=None)
    not_before = _not_before(latest, features, state, readiness, now)
    valid_until = not_before + timedelta(hours=config.recommendation_valid_hours)
    recommended_for = not_before.astimezone(ZoneInfo(timezone)).date()
    candidate = selected.candidate
    observations = quality.missing_categories if quality.overall < 0.7 else ()
    reasons = tuple(dict.fromkeys((*safety_reasons, *state.reason_codes)))
    if candidate.decision == RunDecision.REST or candidate.kind is None:
        return Prescription(
            RunDecision.REST,
            None,
            recommended_for,
            not_before,
            valid_until,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            quality.overall,
            reasons or ("RECOVERY_DAY",),
            observations,
        )
    readiness_multiplier = min(1.10, max(0.75, 0.75 + state.readiness_score * 0.35))
    goal_multiplier = 1.0
    if goal in {RunningGoalType.FIRST_HALF, RunningGoalType.FIRST_MARATHON}:
        goal_multiplier = 1.05
    risk_multiplier = 0.8 if features.break_days >= config.break_reduced_capability_days else 1.0
    preferred = round(
        features.base_duration_sec
        * candidate.duration_multiplier
        * goal_multiplier
        * readiness_multiplier
        * risk_multiplier
    )
    cap = candidate.maximum_duration_sec
    if features.break_days >= config.return_to_running_days:
        cap = min(cap, config.return_duration_cap_sec)
    if readiness.available_time_sec is not None:
        cap = min(cap, readiness.available_time_sec)
    duration = _round_seconds(min(cap, max(candidate.minimum_duration_sec, preferred)))
    pace = features.robust_pace_sec_per_km if quality.pace >= 0.45 else None
    distance = (
        None
        if pace is None
        else _round_distance(duration * 1000 // _pace_for(candidate.kind, pace))
    )
    pace_range = _pace_range(candidate.kind, pace)
    hr = features.robust_hr if quality.heart_rate >= 0.55 else None
    hr_range = (None, None) if hr is None else (round(hr * 0.88), round(hr * 1.04))
    short_duration = _round_seconds(max(candidate.minimum_duration_sec, duration * 70 // 100))
    short = None
    if short_duration < duration:
        short = ShortAlternative(
            short_duration,
            None if distance is None else min(distance, _round_distance(distance * 70 // 100)),
            candidate.kind,
        )
    bounds = SafeBounds(
        candidate.minimum_duration_sec,
        cap,
        None if pace is None else _round_distance(cap * 1000 // _pace_for(candidate.kind, pace)),
        candidate.kind,
    )
    return Prescription(
        RunDecision.RUN,
        candidate.kind,
        recommended_for,
        not_before,
        valid_until,
        duration,
        distance,
        pace_range[0],
        pace_range[1],
        hr_range[0],
        hr_range[1],
        candidate.rpe_min,
        candidate.rpe_max,
        short,
        bounds,
        quality.overall,
        reasons or ("GOAL_ALIGNED",),
        observations,
    )


def _not_before(
    latest: RunFact | None,
    features: TrainingFeatures,
    state: AthleteState,
    readiness: ReadinessValues,
    now: datetime,
) -> datetime:
    if latest is None:
        base = now
    else:
        classification = next(
            item for item in features.classifications if item.activity_id == latest.activity_id
        )
        hours = 24
        if classification.kind == HistoricalRunKind.STEADY:
            hours = 36
        elif classification.kind.hard or classification.kind == HistoricalRunKind.LONG_RUN:
            hours = 48
        base = max(now, latest.ended_at + timedelta(hours=hours))
    extra = 0
    if state.moderate_pain or state.high_external_load:
        extra += 12
    if state.readiness_score < 0.45:
        extra += 12
    return base + timedelta(hours=extra)


def _pace_for(kind: RecommendedRunKind, sustainable: int) -> int:
    return round(
        sustainable
        * {
            RecommendedRunKind.RECOVERY: 1.12,
            RecommendedRunKind.EASY: 1.06,
            RecommendedRunKind.STEADY: 1.0,
            RecommendedRunKind.TEMPO: 0.92,
            RecommendedRunKind.LONG_RUN: 1.08,
        }[kind]
    )


def _pace_range(kind: RecommendedRunKind, pace: int | None) -> tuple[int | None, int | None]:
    if pace is None:
        return None, None
    center = _pace_for(kind, pace)
    return _round_pace(center - 10), _round_pace(center + 15)


def _round_seconds(value: int) -> int:
    return max(300, round(value / 300) * 300)


def _round_distance(value: int) -> int:
    return max(500, round(value / 500) * 500)


def _round_pace(value: int) -> int:
    return max(120, round(value / 5) * 5)
