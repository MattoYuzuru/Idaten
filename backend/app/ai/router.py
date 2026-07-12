import asyncio

from app.ai.contracts import AiError, AiRoute, AiTask
from app.ai.registry import AiRegistry
from app.ai.schemas import (
    ActivityExtractionRequest,
    ActivityExtractionResult,
    ReadinessExtractionRequest,
    ReadinessExtractionResult,
    VoiceTranscriptionRequest,
    VoiceTranscriptionResult,
)


class AiRouter:
    def __init__(
        self,
        registry: AiRegistry,
        routes: dict[AiTask, AiRoute],
        *,
        enabled: bool,
        timeout_seconds: float,
        retries: int,
    ) -> None:
        self.registry = registry
        self.routes = dict(routes)
        self.enabled = enabled
        self.timeout_seconds = timeout_seconds
        self.retries = max(0, retries)

    async def activity(self, request: ActivityExtractionRequest) -> ActivityExtractionResult:
        result = await self._execute(AiTask.ACTIVITY_EXTRACTION, request)
        if not isinstance(result, ActivityExtractionResult):
            raise AiError("Provider вернул неверный тип результата.", code="PROVIDER_RESPONSE")
        return result

    async def readiness(self, request: ReadinessExtractionRequest) -> ReadinessExtractionResult:
        result = await self._execute(AiTask.READINESS_EXTRACTION, request)
        if not isinstance(result, ReadinessExtractionResult):
            raise AiError("Provider вернул неверный тип результата.", code="PROVIDER_RESPONSE")
        return result

    async def transcribe(self, request: VoiceTranscriptionRequest) -> VoiceTranscriptionResult:
        result = await self._execute(AiTask.VOICE_TRANSCRIPTION, request)
        if not isinstance(result, VoiceTranscriptionResult):
            raise AiError("Provider вернул неверный тип результата.", code="PROVIDER_RESPONSE")
        return result

    def route(self, task: AiTask) -> AiRoute:
        if not self.enabled:
            raise AiError("Внешняя обработка отключена.", code="PROVIDER_DISABLED")
        route = self.routes.get(task)
        if route is None or not route.model.strip():
            raise AiError("AI task не настроен.", code="TASK_DISABLED")
        provider = self.registry.provider(route.provider)
        if task not in provider.capabilities:
            raise AiError("Provider не поддерживает task.", code="TASK_UNSUPPORTED")
        return route

    async def _execute(self, task: AiTask, request: object) -> object:
        route = self.route(task)
        provider = self.registry.provider(route.provider)
        for attempt in range(self.retries + 1):
            try:
                return await asyncio.wait_for(
                    provider.execute(task, request, route.model),
                    timeout=self.timeout_seconds,
                )
            except TimeoutError as error:
                if attempt == self.retries:
                    raise AiError(
                        "Provider не ответил вовремя.", code="PROVIDER_TIMEOUT"
                    ) from error
            except AiError:
                if attempt == self.retries:
                    raise
            except Exception as error:
                if attempt == self.retries:
                    raise AiError(
                        "Provider временно недоступен.", code="PROVIDER_FAILED"
                    ) from error
        raise AiError("Provider временно недоступен.", code="PROVIDER_FAILED")
