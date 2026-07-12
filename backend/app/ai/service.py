import hashlib
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.contracts import AiError, AiTask
from app.ai.router import AiRouter
from app.ai.schemas import (
    ReadinessExtractionRequest,
    VoiceTranscriptionRequest,
)
from app.assisted.models import AiAttempt, AiAttemptStatus
from app.assisted.repository import AssistedRepository
from app.assisted.schemas import AssistedError
from app.assisted.service import AssistedActivityService
from app.readiness.domain import CheckInInputSource, CheckInPhase, CheckInStatus
from app.readiness.repository import ReadinessRepository
from app.readiness.schemas import ReadinessDraft, ReadinessError, ReadinessValues
from app.readiness.service import ReadinessService
from app.users.repository import UserRepository


class AiReadinessInputService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        router: AiRouter,
        access: AssistedActivityService,
        readiness: ReadinessService,
        *,
        max_text_chars: int,
        max_audio_bytes: int,
    ) -> None:
        self.session_factory = session_factory
        self.router = router
        self.access = access
        self.readiness = readiness
        self.max_text_chars = max_text_chars
        self.max_audio_bytes = max_audio_bytes

    async def pending(self, telegram_user_id: int, field: str) -> ReadinessDraft | None:
        if field not in {"ai_text", "ai_voice"}:
            return None
        async with self.session_factory() as session:
            user_row = await UserRepository(session).get_by_telegram_id(telegram_user_id)
            if user_row is None:
                return None
            user = user_row[0]
            for phase in (CheckInPhase.POST_RUN, CheckInPhase.PRE_RUN):
                draft = await ReadinessRepository(session).active_draft(user.id, phase)
                if draft is not None and draft.pending_field == field:
                    return ReadinessService._dto(draft)
        return None

    async def extract_text(
        self,
        telegram_user_id: int,
        draft_id: uuid.UUID,
        text: str,
        *,
        source: CheckInInputSource = CheckInInputSource.AI_TEXT,
        moment: datetime | None = None,
    ) -> ReadinessDraft:
        normalized = text.strip()
        if not normalized or len(normalized) > self.max_text_chars:
            raise AiError("Текст пустой или слишком длинный.", code="TEXT_SIZE")
        now = moment or datetime.now(UTC)
        digest = hashlib.sha256(normalized.encode()).hexdigest()
        attempt_id, timezone, phase = await self._start_attempt(
            telegram_user_id,
            draft_id,
            AiTask.READINESS_EXTRACTION,
            digest,
            now,
            pending_field=("ai_voice" if source == CheckInInputSource.AI_VOICE else "ai_text"),
        )
        try:
            result = await self.router.readiness(
                ReadinessExtractionRequest(
                    normalized,
                    timezone,
                    now.astimezone(ZoneInfo(timezone)).date(),
                )
            )
            self._validate_extracted(result.values, phase)
            return await self._finish_readiness(
                telegram_user_id,
                draft_id,
                attempt_id,
                result.values,
                result.provider_request_id,
                source,
            )
        except (AiError, AssistedError, ReadinessError) as error:
            await self._fail_attempt(attempt_id, getattr(error, "code", "INVALID_READINESS"))
            raise

    async def extract_voice(
        self,
        telegram_user_id: int,
        draft_id: uuid.UUID,
        audio: bytes,
        media_type: str,
        *,
        moment: datetime | None = None,
    ) -> ReadinessDraft:
        if not audio or len(audio) > self.max_audio_bytes:
            raise AiError("Голосовое сообщение слишком большое.", code="AUDIO_SIZE")
        if media_type not in {"audio/ogg", "audio/opus", "application/ogg"}:
            raise AiError("Неподдерживаемый формат аудио.", code="AUDIO_TYPE")
        now = moment or datetime.now(UTC)
        digest = hashlib.sha256(audio).hexdigest()
        attempt_id, _timezone, _phase = await self._start_attempt(
            telegram_user_id,
            draft_id,
            AiTask.VOICE_TRANSCRIPTION,
            digest,
            now,
            pending_field="ai_voice",
        )
        try:
            transcript = await self.router.transcribe(VoiceTranscriptionRequest(audio, media_type))
            await self._finish_attempt(attempt_id, transcript.provider_request_id)
        except AiError as error:
            await self._fail_attempt(attempt_id, error.code)
            raise
        return await self.extract_text(
            telegram_user_id,
            draft_id,
            transcript.transcript,
            source=CheckInInputSource.AI_VOICE,
            moment=now,
        )

    async def _start_attempt(
        self,
        telegram_user_id: int,
        draft_id: uuid.UUID,
        task: AiTask,
        digest: str,
        now: datetime,
        *,
        pending_field: str,
    ) -> tuple[uuid.UUID, str, CheckInPhase]:
        async with self.session_factory.begin() as session:
            user = await self.access.require_allowed_user(session, telegram_user_id, task)
            draft = await ReadinessRepository(session).by_id(draft_id, for_update=True)
            if (
                draft is None
                or draft.user_id != user.id
                or draft.status != CheckInStatus.DRAFT
                or draft.pending_field != pending_field
            ):
                raise AiError("Readiness draft не найден.", code="DRAFT_NOT_FOUND")
            repository = AssistedRepository(session)
            await self.access.check_limits(repository, user, now)
            route = self.router.route(task)
            attempt = AiAttempt(
                user_id=user.id,
                draft_id=None,
                task=task,
                input_method=None,
                input_sha256=digest,
                provider=route.provider,
                provider_model=route.model,
                status=AiAttemptStatus.PROCESSING,
                created_at=now,
            )
            repository.add(attempt)
            await session.flush()
            return attempt.id, user.timezone, draft.phase

    async def _finish_readiness(
        self,
        telegram_user_id: int,
        draft_id: uuid.UUID,
        attempt_id: uuid.UUID,
        values: ReadinessValues,
        provider_request_id: str | None,
        source: CheckInInputSource,
    ) -> ReadinessDraft:
        async with self.session_factory.begin() as session:
            user = await self.access.require_allowed_user(
                session, telegram_user_id, AiTask.READINESS_EXTRACTION
            )
            draft = await ReadinessRepository(session).by_id(draft_id, for_update=True)
            expected_pending = "ai_voice" if source == CheckInInputSource.AI_VOICE else "ai_text"
            if (
                draft is None
                or draft.user_id != user.id
                or draft.status != CheckInStatus.DRAFT
                or draft.pending_field != expected_pending
            ):
                raise AiError("Readiness draft закрыт.", code="DRAFT_NOT_FOUND")
            current = ReadinessService._values(draft)
            selected = values
            selected_source = source
            if current.sleep_summary_id is not None:
                if values.sleep_quality is None and values.sleep_duration_sec is None:
                    selected = replace(
                        values,
                        sleep_quality=current.sleep_quality,
                        sleep_duration_sec=current.sleep_duration_sec,
                        sleep_ended_at=current.sleep_ended_at,
                        sleep_summary_id=current.sleep_summary_id,
                    )
                    selected_source = CheckInInputSource.MERGED
                else:
                    selected = replace(
                        values,
                        sleep_ended_at=None,
                        sleep_summary_id=None,
                    )
            ReadinessService._assign(draft, selected)
            draft.source = selected_source
            draft.pending_field = None
            draft.version += 1
            await self._finish_attempt_in_session(session, attempt_id, provider_request_id)
            return ReadinessService._dto(draft)

    async def _finish_attempt(self, attempt_id: uuid.UUID, request_id: str | None) -> None:
        async with self.session_factory.begin() as session:
            await self._finish_attempt_in_session(session, attempt_id, request_id)

    @staticmethod
    async def _finish_attempt_in_session(
        session: AsyncSession, attempt_id: uuid.UUID, request_id: str | None
    ) -> None:
        attempt = await AssistedRepository(session).attempt_by_id(attempt_id, for_update=True)
        if attempt is None:
            raise AiError("AI attempt не найден.", code="ATTEMPT_NOT_FOUND")
        attempt.status = AiAttemptStatus.SUCCEEDED
        attempt.provider_request_id = request_id
        attempt.finished_at = datetime.now(UTC)

    async def _fail_attempt(self, attempt_id: uuid.UUID, error_code: str) -> None:
        async with self.session_factory.begin() as session:
            attempt = await AssistedRepository(session).attempt_by_id(attempt_id, for_update=True)
            if attempt is not None:
                attempt.status = AiAttemptStatus.FAILED
                attempt.error_code = error_code[:64]
                attempt.finished_at = datetime.now(UTC)

    @staticmethod
    def _validate_extracted(values: ReadinessValues, phase: CheckInPhase) -> None:
        ReadinessService._validate_values(values, phase, confirmed=False)
        if values.pain_present is True and any(
            item is None
            for item in (
                values.pain_severity,
                values.pain_location,
                values.pain_affects_movement,
                values.pain_is_new,
                values.pain_is_worsening,
            )
        ):
            raise AiError("Provider вернул неполные pain fields.", code="PROVIDER_RESPONSE")
