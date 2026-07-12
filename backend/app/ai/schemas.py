from dataclasses import dataclass
from datetime import date, time

from app.activities.models import DraftInputMethod
from app.readiness.schemas import ReadinessValues


@dataclass(frozen=True, slots=True)
class ActivityExtractionRequest:
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
class ActivityExtractionResult:
    run: ExtractedRun
    provider_request_id: str | None


@dataclass(frozen=True, slots=True)
class ReadinessExtractionRequest:
    text: str
    timezone: str
    local_date: date


@dataclass(frozen=True, slots=True)
class ReadinessExtractionResult:
    values: ReadinessValues
    provider_request_id: str | None


@dataclass(frozen=True, slots=True)
class VoiceTranscriptionRequest:
    audio: bytes
    media_type: str


@dataclass(frozen=True, slots=True)
class VoiceTranscriptionResult:
    transcript: str
    provider_request_id: str | None
