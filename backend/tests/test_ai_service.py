import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.ai.contracts import AiError, AiRoute, AiTask
from app.ai.registry import AiRegistry
from app.ai.router import AiRouter
from app.ai.schemas import (
    ReadinessExtractionRequest,
    ReadinessExtractionResult,
    VoiceTranscriptionRequest,
    VoiceTranscriptionResult,
)
from app.ai.service import AiReadinessInputService
from app.assisted.models import AiAttempt, AiAttemptStatus, ExternalAiAccessStatus
from app.assisted.schemas import AssistedError
from app.assisted.service import AssistedActivityService
from app.core.config import Settings
from app.db.base import Base
from app.readiness.domain import CheckInInputSource, CheckInPhase
from app.readiness.schemas import ReadinessError, ReadinessValues
from app.services import AppServices, build_services
from app.users.schemas import TelegramIdentity

NOW = datetime(2026, 7, 12, 12, tzinfo=UTC)
RAW_TEXT = "Готовность 4, усталость 3, мышцы 2, боли и симптомов нет, нагрузка 1"
TRANSCRIPT = "Готовность четыре, усталость три, боли нет"


class FakeAiProvider:
    name = "FAKE"
    capabilities = frozenset(AiTask)

    def __init__(self) -> None:
        self.calls: list[tuple[AiTask, object, str]] = []
        self.values = complete_values()
        self.error: AiError | None = None

    async def execute(self, task: AiTask, request: object, model: str) -> object:
        self.calls.append((task, request, model))
        if self.error is not None:
            raise self.error
        if task == AiTask.READINESS_EXTRACTION:
            assert isinstance(request, ReadinessExtractionRequest)
            return ReadinessExtractionResult(self.values, "readiness-request")
        if task == AiTask.VOICE_TRANSCRIPTION:
            assert isinstance(request, VoiceTranscriptionRequest)
            return VoiceTranscriptionResult(TRANSCRIPT, "voice-request")
        raise AiError("unsupported", code="TASK_UNSUPPORTED")


class RevokingAiProvider(FakeAiProvider):
    access: AssistedActivityService

    async def execute(self, task: AiTask, request: object, model: str) -> object:
        result = await super().execute(task, request, model)
        await self.access.decide_access(1, 42, allow=False)
        return result


def complete_values() -> ReadinessValues:
    return ReadinessValues(
        overall_readiness=4,
        general_fatigue=3,
        muscle_soreness=2,
        external_load=1,
        pain_present=False,
        illness_symptoms=False,
    )


def identity() -> TelegramIdentity:
    return TelegramIdentity(42, 42, "runner", "Runner")


def ai_router(provider: FakeAiProvider) -> AiRouter:
    registry = AiRegistry()
    registry.register(provider)
    routes = {task: AiRoute("FAKE", f"fake-{task.value.casefold()}") for task in AiTask}
    return AiRouter(registry, routes, enabled=True, timeout_seconds=1, retries=0)


@pytest.fixture
async def ai_context() -> AsyncIterator[
    tuple[
        AppServices,
        async_sessionmaker[AsyncSession],
        AssistedActivityService,
        AiReadinessInputService,
        FakeAiProvider,
    ]
]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    services = build_services(
        session_factory,
        Settings(database_url="sqlite+aiosqlite://", default_timezone="UTC", _env_file=None),
    )
    provider = FakeAiProvider()
    router = ai_router(provider)
    access = AssistedActivityService(
        session_factory,
        services.users,
        router,
        enabled=True,
        owner_telegram_user_id=1,
        max_text_chars=4_000,
        max_image_bytes=1_000_000,
        max_image_pixels=20_000_000,
        daily_user_limit=5,
        monthly_global_limit=100,
    )
    readiness_ai = AiReadinessInputService(
        session_factory,
        router,
        access,
        services.readiness,
        max_text_chars=4_000,
        max_audio_bytes=1_000_000,
    )
    await services.users.register(identity())
    request = await access.accept_consent(identity(), task=AiTask.READINESS_EXTRACTION)
    assert request.status == ExternalAiAccessStatus.PENDING
    await access.decide_access(1, 42, allow=True)
    yield services, session_factory, access, readiness_ai, provider
    await engine.dispose()


async def ai_draft(
    services: AppServices,
    *,
    source: CheckInInputSource,
    pending: str,
) -> uuid.UUID:
    draft = await services.readiness.start_draft(42, CheckInPhase.POST_RUN, source=source)
    await services.readiness.set_pending_field(42, draft.check_in_id, pending)
    return draft.check_in_id


@pytest.mark.asyncio
async def test_registry_extension_routes_fake_provider_without_vendor_branch() -> None:
    provider = FakeAiProvider()
    router = ai_router(provider)

    result = await router.readiness(ReadinessExtractionRequest(RAW_TEXT, "UTC", NOW.date()))

    assert result.values == complete_values()
    assert provider.calls[0][0] == AiTask.READINESS_EXTRACTION
    assert provider.calls[0][2] == "fake-readiness_extraction"


@pytest.mark.asyncio
async def test_text_readiness_is_typed_and_audit_contains_only_hash_and_metadata(
    ai_context: tuple[
        AppServices,
        async_sessionmaker[AsyncSession],
        AssistedActivityService,
        AiReadinessInputService,
        FakeAiProvider,
    ],
) -> None:
    services, session_factory, _access, readiness_ai, provider = ai_context
    draft_id = await ai_draft(services, source=CheckInInputSource.AI_TEXT, pending="ai_text")

    result = await readiness_ai.extract_text(42, draft_id, RAW_TEXT, moment=NOW)

    assert result.values == complete_values()
    assert result.source == CheckInInputSource.AI_TEXT
    assert result.pending_field is None
    task, request, _model = provider.calls[0]
    assert task == AiTask.READINESS_EXTRACTION
    assert isinstance(request, ReadinessExtractionRequest)
    assert request.text == RAW_TEXT
    assert set(request.__dataclass_fields__) == {"text", "timezone", "local_date"}
    async with session_factory() as session:
        attempt = (await session.scalars(select(AiAttempt))).one()
    assert attempt.task == AiTask.READINESS_EXTRACTION
    assert attempt.status == AiAttemptStatus.SUCCEEDED
    assert attempt.input_sha256 == hashlib.sha256(RAW_TEXT.encode()).hexdigest()
    assert RAW_TEXT not in repr(attempt.__dict__)


@pytest.mark.asyncio
async def test_voice_pipeline_creates_two_audits_without_audio_or_transcript(
    ai_context: tuple[
        AppServices,
        async_sessionmaker[AsyncSession],
        AssistedActivityService,
        AiReadinessInputService,
        FakeAiProvider,
    ],
) -> None:
    services, session_factory, _access, readiness_ai, provider = ai_context
    draft_id = await ai_draft(services, source=CheckInInputSource.AI_VOICE, pending="ai_voice")
    audio = b"ephemeral ogg bytes"

    result = await readiness_ai.extract_voice(42, draft_id, audio, "audio/ogg", moment=NOW)

    assert result.source == CheckInInputSource.AI_VOICE
    assert [call[0] for call in provider.calls] == [
        AiTask.VOICE_TRANSCRIPTION,
        AiTask.READINESS_EXTRACTION,
    ]
    async with session_factory() as session:
        attempts = tuple(
            (
                await session.scalars(
                    select(AiAttempt).order_by(AiAttempt.created_at, AiAttempt.id)
                )
            ).all()
        )
    assert {attempt.task for attempt in attempts} == {
        AiTask.VOICE_TRANSCRIPTION,
        AiTask.READINESS_EXTRACTION,
    }
    serialized = repr([attempt.__dict__ for attempt in attempts])
    assert audio.decode() not in serialized
    assert TRANSCRIPT not in serialized


@pytest.mark.asyncio
async def test_out_of_range_provider_result_fails_attempt_and_keeps_draft_editable(
    ai_context: tuple[
        AppServices,
        async_sessionmaker[AsyncSession],
        AssistedActivityService,
        AiReadinessInputService,
        FakeAiProvider,
    ],
) -> None:
    services, session_factory, _access, readiness_ai, provider = ai_context
    provider.values = ReadinessValues(overall_readiness=9)
    draft_id = await ai_draft(services, source=CheckInInputSource.AI_TEXT, pending="ai_text")

    with pytest.raises(ReadinessError):
        await readiness_ai.extract_text(42, draft_id, RAW_TEXT, moment=NOW)

    draft = await services.readiness.get(42, draft_id)
    assert draft.pending_field == "ai_text"
    async with session_factory() as session:
        attempt = (await session.scalars(select(AiAttempt))).one()
    assert attempt.status == AiAttemptStatus.FAILED
    assert attempt.error_code == "INVALID_READINESS"


@pytest.mark.asyncio
async def test_access_revoke_after_call_prevents_draft_update_and_is_audited(
    ai_context: tuple[
        AppServices,
        async_sessionmaker[AsyncSession],
        AssistedActivityService,
        AiReadinessInputService,
        FakeAiProvider,
    ],
) -> None:
    services, session_factory, access, _readiness_ai, _provider = ai_context
    provider = RevokingAiProvider()
    router = ai_router(provider)
    provider.access = access
    readiness_ai = AiReadinessInputService(
        session_factory,
        router,
        access,
        services.readiness,
        max_text_chars=4_000,
        max_audio_bytes=1_000_000,
    )
    draft_id = await ai_draft(services, source=CheckInInputSource.AI_TEXT, pending="ai_text")

    with pytest.raises(AssistedError) as captured:
        await readiness_ai.extract_text(42, draft_id, RAW_TEXT, moment=NOW)

    assert getattr(captured.value, "code", None) == "ACCESS_DENIED"
    draft = await services.readiness.get(42, draft_id)
    assert draft.values.overall_readiness is None
    async with session_factory() as session:
        attempt = (await session.scalars(select(AiAttempt))).one()
    assert attempt.status == AiAttemptStatus.FAILED
    assert attempt.error_code == "ACCESS_DENIED"
