import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class HealthConnectError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class LinkCode:
    code: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class LinkedDevice:
    device_id: uuid.UUID
    token: str
    scope: str


@dataclass(frozen=True, slots=True)
class HealthConnectSample:
    timestamp: datetime
    latitude: float | None = None
    longitude: float | None = None
    elevation_m: float | None = None
    heart_rate: int | None = None
    speed_mps: float | None = None
    cadence_spm: float | None = None


@dataclass(frozen=True, slots=True)
class HealthConnectSplit:
    index: int
    distance_m: int
    elapsed_time_sec: int
    moving_time_sec: int | None = None


@dataclass(frozen=True, slots=True)
class HealthConnectRun:
    external_id: str
    started_at: datetime
    timezone: str
    distance_m: int
    elapsed_time_sec: int
    moving_time_sec: int | None = None
    title: str | None = None
    avg_hr: int | None = None
    max_hr: int | None = None
    splits: tuple[HealthConnectSplit, ...] = ()
    samples: tuple[HealthConnectSample, ...] = ()


class SyncItemState(StrEnum):
    SAVED = "saved"
    DUPLICATE = "duplicate"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class SyncItemResult:
    external_id: str
    state: SyncItemState
    activity_id: uuid.UUID | None = None
    error_code: str | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class SyncBatchResult:
    items: tuple[SyncItemResult, ...]
    cursor: str | None


@dataclass(frozen=True, slots=True)
class DeviceStatus:
    device_id: uuid.UUID
    name: str
    model: str | None
    scope: str
    last_sync_cursor: str | None
    last_sync_at: datetime | None
    last_sync_status: str
    last_sync_error: str | None


@dataclass(frozen=True, slots=True)
class DeviceSummary:
    device_id: uuid.UUID
    name: str
    model: str | None
    revoked: bool
    last_sync_at: datetime | None
