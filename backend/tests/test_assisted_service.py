import struct
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.activities.models import Activity, ActivityVisibility, DraftInputMethod, SourceType
from app.activities.schemas import ActivityInputError, ManualRunInput, PossibleDuplicateError
from app.ai.contracts import AiError, AiRoute, AiTask
from app.ai.registry import AiRegistry
from app.ai.router import AiRouter
from app.assisted.models import (
    AiAttempt,
    AiAttemptStatus,
    ExternalAiAccessStatus,
)
from app.assisted.schemas import (
    AssistedError,
    ExtractedRun,
    ExtractionRequest,
    ExtractionResult,
    InputGateStatus,
)
from app.assisted.service import AssistedActivityService
from app.core.config import Settings
from app.db.base import Base
from app.ingestion.models import RawArtifact
from app.services import AppServices, build_services
from app.users.schemas import TelegramIdentity


class FakeExtractionProvider:
    name = "FAKE"
    capabilities = frozenset({AiTask.ACTIVITY_EXTRACTION})

    def __init__(self, run: ExtractedRun) -> None:
        self.run = run
        self.requests: list[ExtractionRequest] = []

    async def execute(self, task: AiTask, request: object, model: str) -> object:
        assert task == AiTask.ACTIVITY_EXTRACTION
        assert model == "fake-cheap-vision"
        assert isinstance(request, ExtractionRequest)
        self.requests.append(request)
        return ExtractionResult(self.run, "request-1")


def router_for(provider: FakeExtractionProvider, *, retries: int = 0) -> AiRouter:
    registry = AiRegistry()
    registry.register(provider)
    return AiRouter(
        registry,
        {AiTask.ACTIVITY_EXTRACTION: AiRoute("FAKE", "fake-cheap-vision")},
        enabled=True,
        timeout_seconds=1,
        retries=retries,
    )


@pytest.fixture
async def assisted_context() -> AsyncIterator[
    tuple[AppServices, AssistedActivityService, FakeExtractionProvider]
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
        Settings(
            database_url="sqlite+aiosqlite://", default_timezone="Europe/Moscow", _env_file=None
        ),
    )
    provider = FakeExtractionProvider(
        ExtractedRun(
            is_run=True,
            local_date=date(2026, 7, 8),
            local_time=time(7, 30),
            distance_m=10_000,
            elapsed_time_sec=3_600,
            avg_hr=151,
        )
    )
    assisted = AssistedActivityService(
        session_factory,
        services.users,
        router_for(provider),
        enabled=True,
        owner_telegram_user_id=1,
        max_text_chars=4_000,
        max_image_bytes=1_000_000,
        max_image_pixels=20_000_000,
        daily_user_limit=5,
        monthly_global_limit=100,
    )
    yield services, assisted, provider
    await engine.dispose()


def identity() -> TelegramIdentity:
    return TelegramIdentity(42, 42, "runner", "Матвей")


async def allow(assisted: AssistedActivityService) -> None:
    request = await assisted.accept_consent(identity())
    assert request.status == ExternalAiAccessStatus.PENDING
    await assisted.decide_access(1, 42, allow=True)


@pytest.mark.asyncio
async def test_consent_access_and_owner_authorization(
    assisted_context: tuple[AppServices, AssistedActivityService, FakeExtractionProvider],
) -> None:
    _services, assisted, _provider = assisted_context
    gate = await assisted.gate(identity(), DraftInputMethod.TEXT)
    assert gate.status == InputGateStatus.CONSENT_REQUIRED

    request = await assisted.accept_consent(identity())
    assert request.notify_owner
    await assisted.mark_notification_sent(42)
    repeated = await assisted.accept_consent(identity())
    assert repeated.status == ExternalAiAccessStatus.PENDING
    assert not repeated.notify_owner
    with pytest.raises(AssistedError) as captured:
        await assisted.decide_access(999, 42, allow=True)
    assert captured.value.code == "OWNER_REQUIRED"

    await assisted.decide_access(1, 42, allow=True)
    ready = await assisted.gate(identity(), DraftInputMethod.TEXT)
    assert ready.status == InputGateStatus.READY
    await assisted.decide_access(1, 42, allow=False)
    revoked = await assisted.gate(identity(), DraftInputMethod.TEXT)
    assert revoked.status == InputGateStatus.ACCESS_REVOKED


@pytest.mark.asyncio
async def test_text_extraction_persists_only_typed_private_activity(
    assisted_context: tuple[AppServices, AssistedActivityService, FakeExtractionProvider],
) -> None:
    services, assisted, provider = assisted_context
    await allow(assisted)
    draft_id = await assisted.start_draft(42, DraftInputMethod.TEXT)
    raw = "8 июля пробежал 10 км за час"

    await assisted.extract_text(42, draft_id, raw)
    draft = await services.activities.manual_draft(42, draft_id)
    result = await services.activities.confirm_manual_draft(42, draft_id)

    assert draft.complete
    assert provider.requests[0].text == raw
    assert result.created
    async with services.activities.session_factory() as session:
        activity = await session.get(Activity, result.activity.activity_id)
        assert activity is not None
        assert activity.source_type == SourceType.TEXT
        assert activity.visibility == ActivityVisibility.PRIVATE
        attempt = (await session.execute(select(AiAttempt))).scalar_one()
        assert attempt.input_sha256 and raw not in attempt.input_sha256
        assert await session.scalar(select(func.count(RawArtifact.id))) == 0


@pytest.mark.asyncio
async def test_assisted_edit_rechecks_duplicate_before_confirm(
    assisted_context: tuple[AppServices, AssistedActivityService, FakeExtractionProvider],
) -> None:
    services, assisted, _provider = assisted_context
    await services.activities.record_manual_run(
        identity(),
        run=ManualRunInput(
            10_100,
            5_000,
            datetime(2026, 7, 8, 14, tzinfo=UTC),
            "Europe/Moscow",
        ),
    )
    await allow(assisted)
    draft_id = await assisted.start_draft(42, DraftInputMethod.TEXT)
    await assisted.extract_text(42, draft_id, "10 км за час 8 июля")
    draft = await services.activities.manual_draft(42, draft_id)
    assert draft.duplicate_candidates

    with pytest.raises(PossibleDuplicateError):
        await services.activities.confirm_manual_draft(42, draft_id)
    saved = await services.activities.confirm_manual_draft(
        42, draft_id, accept_possible_duplicate=True
    )
    assert saved.created


@pytest.mark.asyncio
async def test_missing_date_blocks_save_and_edit_preserves_extracted_time(
    assisted_context: tuple[AppServices, AssistedActivityService, FakeExtractionProvider],
) -> None:
    services, assisted, provider = assisted_context
    provider.run = ExtractedRun(
        is_run=True,
        local_date=None,
        local_time=time(7, 30),
        distance_m=5_000,
        elapsed_time_sec=1_800,
    )
    await allow(assisted)
    draft_id = await assisted.start_draft(42, DraftInputMethod.TEXT)
    await assisted.extract_text(42, draft_id, "Пробежал 5 км за полчаса")

    draft = await services.activities.manual_draft(42, draft_id)
    assert not draft.complete
    assert not draft.date_confirmed
    assert draft.start_time_known
    with pytest.raises(ActivityInputError, match="Укажите дату"):
        await services.activities.confirm_manual_draft(42, draft_id)

    edited = await services.activities.set_manual_draft_field(42, draft_id, "date", "2026-07-08")
    assert edited.run.started_at.date() == date(2026, 7, 8)
    assert edited.run.started_at.time().replace(tzinfo=None) == time(7, 30)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("daily_limit", "monthly_limit", "error_code"),
    [(0, 100, "DAILY_LIMIT"), (5, 0, "MONTHLY_LIMIT")],
)
async def test_usage_limits_block_before_provider_call(
    assisted_context: tuple[AppServices, AssistedActivityService, FakeExtractionProvider],
    daily_limit: int,
    monthly_limit: int,
    error_code: str,
) -> None:
    services, assisted, provider = assisted_context
    await allow(assisted)
    limited = AssistedActivityService(
        assisted.session_factory,
        services.users,
        router_for(provider),
        enabled=True,
        owner_telegram_user_id=1,
        max_text_chars=4_000,
        max_image_bytes=1_000_000,
        max_image_pixels=20_000_000,
        daily_user_limit=daily_limit,
        monthly_global_limit=monthly_limit,
    )
    draft_id = await limited.start_draft(42, DraftInputMethod.TEXT)

    with pytest.raises(AssistedError) as captured:
        await limited.extract_text(42, draft_id, "5 км за 30 минут")

    assert captured.value.code == error_code
    assert provider.requests == []


@pytest.mark.asyncio
async def test_revoke_is_rechecked_after_provider_and_failed_attempt_is_audited(
    assisted_context: tuple[AppServices, AssistedActivityService, FakeExtractionProvider],
) -> None:
    services, assisted, provider = assisted_context
    await allow(assisted)

    class RevokingProvider(FakeExtractionProvider):
        service: AssistedActivityService

        async def execute(self, task: AiTask, request: object, model: str) -> object:
            assert task == AiTask.ACTIVITY_EXTRACTION
            assert model == "fake-cheap-vision"
            assert isinstance(request, ExtractionRequest)
            self.requests.append(request)
            await self.service.decide_access(1, 42, allow=False)
            return ExtractionResult(self.run, "request-revoked")

    revoking = RevokingProvider(provider.run)
    guarded = AssistedActivityService(
        assisted.session_factory,
        services.users,
        router_for(revoking),
        enabled=True,
        owner_telegram_user_id=1,
        max_text_chars=4_000,
        max_image_bytes=1_000_000,
        max_image_pixels=20_000_000,
        daily_user_limit=5,
        monthly_global_limit=100,
    )
    revoking.service = guarded
    draft_id = await guarded.start_draft(42, DraftInputMethod.TEXT)

    with pytest.raises(AssistedError) as captured:
        await guarded.extract_text(42, draft_id, "10 км за час")

    assert captured.value.code == "ACCESS_DENIED"
    async with guarded.session_factory() as session:
        attempt = (await session.execute(select(AiAttempt))).scalar_one()
    assert attempt.status == AiAttemptStatus.FAILED
    assert attempt.error_code == "ACCESS_DENIED"


@pytest.mark.asyncio
async def test_screenshot_hash_retry_returns_existing_private_activity(
    assisted_context: tuple[AppServices, AssistedActivityService, FakeExtractionProvider],
) -> None:
    services, assisted, _provider = assisted_context
    await allow(assisted)
    image = (
        b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 100, 200) + b"ephemeral"
    )

    first_draft = await assisted.start_draft(42, DraftInputMethod.SCREENSHOT)
    await assisted.extract_image(42, first_draft, image, "image/png")
    first = await services.activities.confirm_manual_draft(42, first_draft)
    second_draft = await assisted.start_draft(42, DraftInputMethod.SCREENSHOT)
    await assisted.extract_image(42, second_draft, image, "application/octet-stream")
    second = await services.activities.confirm_manual_draft(42, second_draft)

    assert first.created
    assert not second.created
    assert second.activity.activity_id == first.activity.activity_id
    async with assisted.session_factory() as session:
        activity = await session.get(Activity, first.activity.activity_id)
        assert activity is not None
        assert activity.source_type == SourceType.SCREENSHOT
        assert activity.visibility == ActivityVisibility.PRIVATE
        assert await session.scalar(select(func.count(Activity.id))) == 1
        assert await session.scalar(select(func.count(RawArtifact.id))) == 0


@pytest.mark.asyncio
async def test_provider_failure_is_bounded_counted_and_leaves_draft_retryable(
    assisted_context: tuple[AppServices, AssistedActivityService, FakeExtractionProvider],
) -> None:
    services, assisted, provider = assisted_context
    await allow(assisted)

    class FailingProvider(FakeExtractionProvider):
        async def execute(self, task: AiTask, request: object, model: str) -> object:
            assert task == AiTask.ACTIVITY_EXTRACTION
            assert model == "fake-cheap-vision"
            assert isinstance(request, ExtractionRequest)
            self.requests.append(request)
            raise AiError("temporary", code="PROVIDER_FAILED")

    failing = FailingProvider(provider.run)
    guarded = AssistedActivityService(
        assisted.session_factory,
        services.users,
        router_for(failing, retries=1),
        enabled=True,
        owner_telegram_user_id=1,
        max_text_chars=4_000,
        max_image_bytes=1_000_000,
        max_image_pixels=20_000_000,
        daily_user_limit=1,
        monthly_global_limit=100,
    )
    draft_id = await guarded.start_draft(42, DraftInputMethod.TEXT)

    with pytest.raises(AssistedError) as failed:
        await guarded.extract_text(42, draft_id, "10 км за час")

    assert failed.value.code == "PROVIDER_FAILED"
    assert len(failing.requests) == 2
    assert await guarded.pending_input(42, DraftInputMethod.TEXT) == draft_id
    with pytest.raises(AssistedError) as limited:
        await guarded.extract_text(42, draft_id, "повтор")
    assert limited.value.code == "DAILY_LIMIT"
    assert len(failing.requests) == 2
    async with guarded.session_factory() as session:
        attempt = (await session.execute(select(AiAttempt))).scalar_one()
    assert attempt.status == AiAttemptStatus.FAILED
    assert attempt.error_code == "PROVIDER_FAILED"
