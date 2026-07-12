from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class AiTask(StrEnum):
    ACTIVITY_EXTRACTION = "ACTIVITY_EXTRACTION"
    READINESS_EXTRACTION = "READINESS_EXTRACTION"
    VOICE_TRANSCRIPTION = "VOICE_TRANSCRIPTION"


class AiError(ValueError):
    def __init__(self, message: str, *, code: str = "AI_ERROR") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class AiRoute:
    provider: str
    model: str


class AiProvider(Protocol):
    name: str
    capabilities: frozenset[AiTask]

    async def execute(self, task: AiTask, request: object, model: str) -> object: ...
