from dataclasses import dataclass
from datetime import date, time
from enum import StrEnum

from app.activities.models import DraftInputMethod
from app.assisted.models import AssistedAccessStatus

CONSENT_VERSION = "activity-extraction-v1"


class AssistedError(ValueError):
    def __init__(self, message: str, *, code: str = "ASSISTED_ERROR") -> None:
        super().__init__(message)
        self.code = code


class InputGateStatus(StrEnum):
    CONSENT_REQUIRED = "CONSENT_REQUIRED"
    ACCESS_PENDING = "ACCESS_PENDING"
    ACCESS_REVOKED = "ACCESS_REVOKED"
    READY = "READY"
    DISABLED = "DISABLED"


@dataclass(frozen=True, slots=True)
class InputGate:
    status: InputGateStatus
    method: DraftInputMethod


@dataclass(frozen=True, slots=True)
class AccessRequestResult:
    status: AssistedAccessStatus
    notify_owner: bool
    telegram_user_id: int
    display_name: str
    username: str | None


@dataclass(frozen=True, slots=True)
class AccessOverview:
    telegram_user_id: int
    status: AssistedAccessStatus | None
    consent_current: bool


@dataclass(frozen=True, slots=True)
class ExtractionRequest:
    method: DraftInputMethod
    timezone: str
    local_date: date
    text: str | None = None
    image: bytes | None = None
    media_type: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractedRun:
    is_run: bool
    local_date: date | None
    local_time: time | None
    distance_m: int | None
    elapsed_time_sec: int | None
    moving_time_sec: int | None = None
    avg_hr: int | None = None
    max_hr: int | None = None
    avg_cadence_spm: int | None = None
    elevation_gain_m: int | None = None
    title: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    run: ExtractedRun
    provider_request_id: str | None
