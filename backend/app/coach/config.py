from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AdaptiveCoachConfig:
    calculator_version: str = "adaptive-features-v1"
    rule_version: str = "adaptive-next-v1"
    fatigue_half_life_days: float = 7.0
    load_half_life_days: float = 28.0
    capability_half_life_days: float = 90.0
    history_half_life_days: float = 365.0
    break_reduced_capability_days: int = 21
    return_to_running_days: int = 42
    recommendation_valid_hours: int = 72
    minimum_run_duration_sec: int = 900
    no_history_duration_sec: int = 1_500
    return_duration_cap_sec: int = 1_800
    readiness_rest_threshold: float = 0.25
    readiness_recovery_threshold: float = 0.45
    low_confidence_threshold: float = 0.45

    def load_factor(self, kind: str) -> float:
        return {
            "RECOVERY": 0.8,
            "EASY": 1.0,
            "STEADY": 1.15,
            "TEMPO": 1.4,
            "INTERVAL": 1.4,
            "LONG_RUN": 1.15,
            "RACE": 1.6,
            "UNKNOWN": 1.1,
        }.get(kind, 1.1)


DEFAULT_CONFIG = AdaptiveCoachConfig()
