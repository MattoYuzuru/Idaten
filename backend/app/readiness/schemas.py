import uuid
from dataclasses import dataclass
from datetime import datetime

from app.readiness.domain import CheckInInputSource, CheckInPhase, CheckInStatus


class ReadinessError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReadinessValues:
    overall_readiness: int | None = None
    general_fatigue: int | None = None
    muscle_soreness: int | None = None
    motivation: int | None = None
    sleep_quality: int | None = None
    sleep_duration_sec: int | None = None
    sleep_ended_at: datetime | None = None
    sleep_summary_id: uuid.UUID | None = None
    external_load: int | None = None
    pain_present: bool | None = None
    pain_severity: int | None = None
    pain_location: str | None = None
    pain_affects_movement: bool | None = None
    pain_is_new: bool | None = None
    pain_is_worsening: bool | None = None
    illness_symptoms: bool | None = None
    available_time_sec: int | None = None
    session_rpe: int | None = None


@dataclass(frozen=True, slots=True)
class ReadinessDraft:
    check_in_id: uuid.UUID
    phase: CheckInPhase
    status: CheckInStatus
    source: CheckInInputSource
    source_confidence: float | None
    values: ReadinessValues
    linked_activity_id: uuid.UUID | None
    pending_field: str | None
    expires_at: datetime
    confirmed_at: datetime | None
    version: int
    telegram_message_id: int | None
