import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime

from app.coach.candidates import ScoredCandidate, select_candidate
from app.coach.config import DEFAULT_CONFIG, AdaptiveCoachConfig
from app.coach.facts import RunFact, TrainingFeatures, calculate_training_features
from app.coach.prescription import Prescription, build_prescription
from app.coach.quality import DataQualityAssessment, assess_data_quality
from app.coach.readiness import AthleteState, assess_readiness, without_stale_sleep
from app.goals.domain import RunningGoalType
from app.readiness.schemas import ReadinessValues


@dataclass(frozen=True, slots=True)
class AdaptiveRecommendation:
    calculator_version: str
    rule_version: str
    features: TrainingFeatures
    quality: DataQualityAssessment
    state: AthleteState
    selected: ScoredCandidate
    prescription: Prescription
    inputs_fingerprint: str

    def facts_json(self) -> dict[str, object]:
        return {
            "calculator_version": self.calculator_version,
            "rule_version": self.rule_version,
            "features": self.features.as_json(),
            "quality": self.quality.as_json(),
            "readiness": self.state.as_json(),
        }

    def rule_result_json(self) -> dict[str, object]:
        return {
            "rule_version": self.rule_version,
            "selected": self.selected.as_json(),
            "prescription": self.prescription.as_json(),
            "inputs_fingerprint": self.inputs_fingerprint,
        }


def calculate_adaptive_recommendation(
    runs: tuple[RunFact, ...],
    goal: RunningGoalType,
    readiness: ReadinessValues,
    *,
    as_of: datetime,
    timezone: str,
    config: AdaptiveCoachConfig = DEFAULT_CONFIG,
) -> AdaptiveRecommendation:
    features = calculate_training_features(runs, as_of=as_of, config=config)
    quality = assess_data_quality(runs, features, readiness, as_of=as_of)
    effective_readiness = without_stale_sleep(readiness, as_of=as_of)
    state = assess_readiness(effective_readiness)
    selected, safety = select_candidate(features, state, quality, effective_readiness, goal, config)
    prescription = build_prescription(
        selected,
        features,
        state,
        quality,
        effective_readiness,
        goal,
        runs,
        as_of=as_of,
        timezone=timezone,
        safety_reasons=safety,
        config=config,
    )
    fingerprint_payload = {
        "calculator_version": config.calculator_version,
        "rule_version": config.rule_version,
        "goal": goal.value,
        "as_of": as_of.isoformat(),
        "runs": [
            {
                "id": str(run.activity_id),
                "started_at": run.started_at.isoformat(),
                "distance_m": run.distance_m,
                "elapsed_time_sec": run.elapsed_time_sec,
                "moving_time_sec": run.moving_time_sec,
                "pace": run.avg_pace_sec_per_km,
                "avg_hr": run.avg_hr,
                "max_hr": run.max_hr,
                "cadence": run.avg_cadence_spm,
                "elevation": run.elevation_gain_m,
                "source": run.source_type.value,
                "title": run.title,
                "rpe": run.session_rpe,
                "start_time_known": run.start_time_known,
            }
            for run in sorted(runs, key=lambda item: (item.started_at, item.activity_id.hex))
        ],
        "readiness": {name: _json_value(value) for name, value in asdict(readiness).items()},
    }
    encoded = json.dumps(
        fingerprint_payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode()
    return AdaptiveRecommendation(
        config.calculator_version,
        config.rule_version,
        features,
        quality,
        state,
        selected,
        prescription,
        hashlib.sha256(encoded).hexdigest(),
    )


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value
