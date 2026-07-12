from dataclasses import dataclass
from enum import StrEnum

from app.activities.models import DraftInputMethod
from app.ai.schemas import (
    ActivityExtractionRequest as ExtractionRequest,
)
from app.ai.schemas import (
    ActivityExtractionResult as ExtractionResult,
)
from app.ai.schemas import (
    ExtractedRun as ExtractedRun,
)
from app.assisted.models import ExternalAiAccessStatus

__all__ = ["ExtractedRun", "ExtractionRequest", "ExtractionResult"]

CONSENT_VERSION = "wellbeing-external-ai-v2"


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
    status: ExternalAiAccessStatus
    notify_owner: bool
    telegram_user_id: int
    display_name: str
    username: str | None


@dataclass(frozen=True, slots=True)
class AccessOverview:
    telegram_user_id: int
    status: ExternalAiAccessStatus | None
    consent_current: bool
