from dataclasses import asdict, dataclass
from enum import StrEnum

from app.coach.config import AdaptiveCoachConfig
from app.coach.facts import TrainingFeatures
from app.coach.quality import DataQualityAssessment
from app.coach.readiness import AthleteState
from app.goals.domain import RunningGoalType
from app.readiness.schemas import ReadinessValues


class RunDecision(StrEnum):
    RUN = "RUN"
    REST = "REST"


class RecommendedRunKind(StrEnum):
    RECOVERY = "RECOVERY"
    EASY = "EASY"
    STEADY = "STEADY"
    TEMPO = "TEMPO"
    LONG_RUN = "LONG_RUN"


@dataclass(frozen=True, slots=True)
class WorkoutCandidate:
    decision: RunDecision
    kind: RecommendedRunKind | None
    duration_multiplier: float
    minimum_duration_sec: int
    maximum_duration_sec: int
    rpe_min: int
    rpe_max: int
    adaptation_value: float
    consistency_value: float
    fatigue_cost: float
    risk_penalty: float
    schedule_cost: float


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    candidate: WorkoutCandidate
    utility: float
    goal_alignment: float

    def as_json(self) -> dict[str, object]:
        result = asdict(self.candidate)
        result["decision"] = self.candidate.decision.value
        result["kind"] = None if self.candidate.kind is None else self.candidate.kind.value
        return {"candidate": result, "utility": self.utility, "goal_alignment": self.goal_alignment}


def select_candidate(
    features: TrainingFeatures,
    state: AthleteState,
    quality: DataQualityAssessment,
    readiness: ReadinessValues,
    goal: RunningGoalType,
    config: AdaptiveCoachConfig,
) -> tuple[ScoredCandidate, tuple[str, ...]]:
    candidates = _generate(config)
    allowed, safety_reasons = _hard_filter(candidates, features, state, quality, readiness, config)
    scored = tuple(_score(candidate, goal, state, quality, readiness) for candidate in allowed)
    selected = max(
        scored,
        key=lambda item: (
            item.utility,
            -_intensity_rank(item.candidate.kind),
            item.candidate.decision.value,
        ),
    )
    return selected, safety_reasons


def _generate(config: AdaptiveCoachConfig) -> tuple[WorkoutCandidate, ...]:
    minimum = config.minimum_run_duration_sec
    return (
        WorkoutCandidate(RunDecision.REST, None, 0.0, 0, 0, 0, 0, 0.25, 0.4, 0.0, 0.0, 0.0),
        WorkoutCandidate(
            RunDecision.RUN,
            RecommendedRunKind.RECOVERY,
            0.75,
            minimum,
            2_400,
            2,
            3,
            0.55,
            0.8,
            0.2,
            0.1,
            0.1,
        ),
        WorkoutCandidate(
            RunDecision.RUN,
            RecommendedRunKind.EASY,
            1.0,
            minimum,
            4_500,
            3,
            4,
            0.75,
            0.9,
            0.35,
            0.15,
            0.15,
        ),
        WorkoutCandidate(
            RunDecision.RUN,
            RecommendedRunKind.STEADY,
            1.0,
            1_200,
            4_800,
            4,
            5,
            0.85,
            0.7,
            0.55,
            0.3,
            0.2,
        ),
        WorkoutCandidate(
            RunDecision.RUN,
            RecommendedRunKind.TEMPO,
            0.9,
            1_500,
            4_200,
            6,
            7,
            1.0,
            0.55,
            0.8,
            0.55,
            0.25,
        ),
        WorkoutCandidate(
            RunDecision.RUN,
            RecommendedRunKind.LONG_RUN,
            1.35,
            2_400,
            7_200,
            3,
            5,
            1.0,
            0.65,
            0.9,
            0.5,
            0.35,
        ),
    )


def _hard_filter(
    candidates: tuple[WorkoutCandidate, ...],
    features: TrainingFeatures,
    state: AthleteState,
    quality: DataQualityAssessment,
    readiness: ReadinessValues,
    config: AdaptiveCoachConfig,
) -> tuple[tuple[WorkoutCandidate, ...], tuple[str, ...]]:
    reasons = list(state.reason_codes)
    if state.hard_rest:
        return tuple(item for item in candidates if item.decision == RunDecision.REST), tuple(
            reasons
        )
    allowed_kinds = set(RecommendedRunKind)
    if state.moderate_pain:
        allowed_kinds &= {RecommendedRunKind.RECOVERY, RecommendedRunKind.EASY}
    if state.readiness_score < config.readiness_recovery_threshold:
        allowed_kinds &= {RecommendedRunKind.RECOVERY}
    if features.break_days >= config.return_to_running_days:
        reasons.append("RETURN_AFTER_LONG_BREAK")
        allowed_kinds &= {RecommendedRunKind.RECOVERY, RecommendedRunKind.EASY}
    if quality.overall < config.low_confidence_threshold or features.run_count < 3:
        reasons.append("CONSERVATIVE_LOW_CONFIDENCE")
        allowed_kinds &= {RecommendedRunKind.RECOVERY, RecommendedRunKind.EASY}
    if (
        features.days_since_hard_run is not None and features.days_since_hard_run < 2
    ) or features.hard_density_28d >= 0.3:
        reasons.append("RECENT_HARD_LOAD")
        allowed_kinds.discard(RecommendedRunKind.TEMPO)
    if state.high_external_load:
        allowed_kinds &= {RecommendedRunKind.RECOVERY, RecommendedRunKind.EASY}
    if (
        readiness.available_time_sec is not None
        and readiness.available_time_sec < config.minimum_run_duration_sec
    ):
        reasons.append("AVAILABLE_TIME_TOO_SHORT")
        return tuple(item for item in candidates if item.decision == RunDecision.REST), tuple(
            reasons
        )
    return tuple(
        item
        for item in candidates
        if item.decision == RunDecision.REST or item.kind in allowed_kinds
    ), tuple(dict.fromkeys(reasons))


def _score(
    candidate: WorkoutCandidate,
    goal: RunningGoalType,
    state: AthleteState,
    quality: DataQualityAssessment,
    readiness: ReadinessValues,
) -> ScoredCandidate:
    goal_alignment = _goal_alignment(goal, candidate.kind)
    adherence = state.readiness_score
    if (
        readiness.available_time_sec is not None
        and candidate.minimum_duration_sec > readiness.available_time_sec
    ):
        adherence = 0.0
    uncertainty = 1 - quality.overall
    utility = (
        2.0 * goal_alignment
        + 1.2 * candidate.adaptation_value
        + 0.8 * candidate.consistency_value
        + 0.8 * adherence
        - 1.6 * candidate.fatigue_cost * (1.2 - state.readiness_score)
        - 2.0 * candidate.risk_penalty
        - 0.8 * candidate.schedule_cost
        - 1.2 * uncertainty
    )
    if candidate.decision == RunDecision.REST and state.readiness_score >= 0.6:
        utility -= 1.5
    return ScoredCandidate(candidate, round(utility, 6), goal_alignment)


def _goal_alignment(goal: RunningGoalType, kind: RecommendedRunKind | None) -> float:
    if kind is None:
        return 0.15
    first = {
        RunningGoalType.FIRST_5K,
        RunningGoalType.FIRST_10K,
        RunningGoalType.FIRST_HALF,
        RunningGoalType.FIRST_MARATHON,
    }
    if goal == RunningGoalType.GENERAL_ENDURANCE:
        return {
            RecommendedRunKind.RECOVERY: 0.55,
            RecommendedRunKind.EASY: 1.0,
            RecommendedRunKind.STEADY: 0.75,
            RecommendedRunKind.TEMPO: 0.45,
            RecommendedRunKind.LONG_RUN: 0.7,
        }[kind]
    if goal in first:
        return {
            RecommendedRunKind.RECOVERY: 0.5,
            RecommendedRunKind.EASY: 1.0,
            RecommendedRunKind.STEADY: 0.65,
            RecommendedRunKind.TEMPO: 0.25,
            RecommendedRunKind.LONG_RUN: 0.9,
        }[kind]
    return {
        RecommendedRunKind.RECOVERY: 0.4,
        RecommendedRunKind.EASY: 0.8,
        RecommendedRunKind.STEADY: 0.75,
        RecommendedRunKind.TEMPO: 1.0,
        RecommendedRunKind.LONG_RUN: 0.85,
    }[kind]


def _intensity_rank(kind: RecommendedRunKind | None) -> int:
    return {
        None: 0,
        RecommendedRunKind.RECOVERY: 1,
        RecommendedRunKind.EASY: 2,
        RecommendedRunKind.STEADY: 3,
        RecommendedRunKind.LONG_RUN: 4,
        RecommendedRunKind.TEMPO: 5,
    }[kind]
