import gzip
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.activities.models import Activity, ActivityVisibility, CoachReport, SourceType
from app.core.config import Settings
from app.db.base import Base
from app.groups.models import ShareLevel
from app.groups.schemas import GroupError
from app.health_connect.models import (
    Device,
    DeviceLinkAttempt,
    DeviceLinkCode,
    DeviceScope,
    HealthConnectSleepSummary,
    HealthConnectSyncBatch,
    OutboxStatus,
    TelegramOutbox,
)
from app.health_connect.outbox import TelegramOutboxService
from app.health_connect.schemas import (
    HealthConnectError,
    HealthConnectRun,
    HealthConnectSample,
    HealthConnectSleep,
    SyncItemState,
)
from app.ingestion.models import ActivitySeries
from app.readiness.domain import CheckInInputSource, CheckInPhase
from app.services import AppServices, build_services
from app.users.schemas import TelegramIdentity


@pytest.fixture
async def health_context(
    tmp_path: Path,
) -> AsyncIterator[tuple[AppServices, async_sessionmaker[AsyncSession]]]:
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
            database_url="sqlite+aiosqlite://",
            storage_path=str(tmp_path / "storage"),
            health_connect_security_pepper="test-pepper",
            health_connect_link_attempt_limit=3,
            health_connect_max_batch_size=2,
            _env_file=None,
        ),
    )
    await services.users.register(identity())
    yield services, session_factory
    await engine.dispose()


def identity() -> TelegramIdentity:
    return TelegramIdentity(
        telegram_user_id=42,
        private_chat_id=42,
        username="runner",
        first_name="Runner",
    )


def run(
    external_id: str = "hc-1",
    *,
    distance_m: int = 5_000,
    samples: tuple[HealthConnectSample, ...] = (),
) -> HealthConnectRun:
    return HealthConnectRun(
        external_id=external_id,
        started_at=datetime(2026, 7, 6, 6, tzinfo=UTC),
        timezone="Europe/Moscow",
        distance_m=distance_m,
        elapsed_time_sec=1_800,
        samples=samples,
    )


async def linked(
    services: AppServices, installation_id: str = "install-1"
) -> tuple[str, uuid.UUID]:
    code = await services.health_connect.start_link_for_identity(identity())
    device = await services.health_connect.complete_link(
        code=code.code,
        installation_id=installation_id,
        device_name="Pixel",
        device_model="Pixel 9",
    )
    return device.token, device.device_id


@pytest.mark.asyncio
async def test_sleep_sync_is_idempotent_and_fresh_longest_prefills_readiness(
    health_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = health_context
    token, _device_id = await linked(services)
    now = datetime(2026, 7, 12, 8, tzinfo=UTC)
    shorter = HealthConnectSleep(
        external_id="sleep-short",
        started_at=now - timedelta(hours=7),
        ended_at=now - timedelta(hours=1),
        duration_sec=6 * 3_600,
        data_origin="com.samsung.health",
        observed_at=now,
    )
    longest = HealthConnectSleep(
        external_id="sleep-long",
        started_at=now - timedelta(hours=9),
        ended_at=now - timedelta(hours=1),
        duration_sec=8 * 3_600,
        data_origin="com.samsung.health",
        observed_at=now,
    )

    first = await services.health_connect.sync_sleep(token, shorter, moment=now)
    await services.health_connect.sync_sleep(token, longest, moment=now)
    repeated = await services.health_connect.sync_sleep(token, shorter, moment=now)
    draft = await services.next_run.start_check_in(42, CheckInPhase.POST_RUN, moment=now)

    assert first.created
    assert not repeated.created
    assert repeated.summary_id == first.summary_id
    assert draft.source == CheckInInputSource.HEALTH_CONNECT
    assert draft.values.sleep_duration_sec == 8 * 3_600
    assert draft.values.sleep_quality is None
    assert draft.values.sleep_summary_id is not None
    assert draft.values.sleep_ended_at == longest.ended_at
    edited = await services.readiness.update(
        42,
        draft.check_in_id,
        replace(draft.values, overall_readiness=4),
        expected_version=draft.version,
    )
    assert edited.source == CheckInInputSource.MERGED
    cleared = await services.readiness.clear_optional(42, draft.check_in_id, "sleep")
    assert cleared.source == CheckInInputSource.MANUAL
    assert cleared.values.sleep_summary_id is None
    assert cleared.values.sleep_duration_sec is None
    async with session_factory() as session:
        summaries = tuple((await session.scalars(select(HealthConnectSleepSummary))).all())
    assert len(summaries) == 2
    assert not hasattr(summaries[0], "stages")
    assert not hasattr(summaries[0], "raw_payload")


@pytest.mark.asyncio
async def test_stale_or_incomplete_sleep_does_not_prefill_and_revoke_rejects_sync(
    health_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, _session_factory = health_context
    token, device_id = await linked(services)
    now = datetime(2026, 7, 12, 8, tzinfo=UTC)
    await services.health_connect.sync_sleep(
        token,
        HealthConnectSleep(
            external_id="stale",
            started_at=now - timedelta(hours=48),
            ended_at=now - timedelta(hours=40),
            duration_sec=8 * 3_600,
        ),
        moment=now,
    )
    await services.health_connect.sync_sleep(
        token,
        HealthConnectSleep(external_id="missing-values"),
        moment=now,
    )

    draft = await services.next_run.start_check_in(42, CheckInPhase.POST_RUN, moment=now)

    assert draft.source == CheckInInputSource.MANUAL
    assert draft.values.sleep_duration_sec is None
    await services.health_connect.revoke_for_user(42, device_id)
    with pytest.raises(HealthConnectError) as revoked:
        await services.health_connect.sync_sleep(
            token,
            HealthConnectSleep(external_id="after-revoke"),
            moment=now,
        )
    assert revoked.value.code == "TOKEN_REVOKED"


@pytest.mark.asyncio
async def test_expired_incorrect_reused_code_and_rate_limit(
    health_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = health_context
    expired = await services.health_connect.start_link_for_identity(identity())
    async with session_factory.begin() as session:
        record = (
            (
                await session.execute(
                    select(DeviceLinkCode).order_by(DeviceLinkCode.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
        assert record is not None
        record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(HealthConnectError, match="истек") as expired_error:
        await services.health_connect.complete_link(
            code=expired.code,
            installation_id="expired-device",
            device_name="Pixel",
            device_model=None,
        )
    assert expired_error.value.code == "LINK_CODE_EXPIRED"

    code = await services.health_connect.start_link_for_identity(identity())
    with pytest.raises(HealthConnectError) as incorrect:
        await services.health_connect.complete_link(
            code="ZZZZZZZZ",
            installation_id="wrong-device",
            device_name="Pixel",
            device_model=None,
        )
    assert incorrect.value.code == "INVALID_LINK_CODE"
    linked_device = await services.health_connect.complete_link(
        code=code.code,
        installation_id="valid-device",
        device_name="Pixel",
        device_model=None,
    )
    with pytest.raises(HealthConnectError) as reused:
        await services.health_connect.complete_link(
            code=code.code,
            installation_id="reuse-device",
            device_name="Pixel",
            device_model=None,
        )
    assert reused.value.code == "LINK_CODE_REUSED"
    assert linked_device.token != code.code

    for _ in range(3):
        with pytest.raises(HealthConnectError):
            await services.health_connect.complete_link(
                code="AAAAAAAA",
                installation_id="limited-device",
                device_name="Pixel",
                device_model=None,
            )
    with pytest.raises(HealthConnectError) as limited:
        await services.health_connect.complete_link(
            code="BBBBBBBB",
            installation_id="limited-device",
            device_name="Pixel",
            device_model=None,
        )
    assert limited.value.code == "RATE_LIMITED"
    async with session_factory() as session:
        assert await session.scalar(select(func.count(DeviceLinkAttempt.id))) >= 6


@pytest.mark.asyncio
async def test_token_is_hashed_scoped_and_revocation_is_immediate(
    health_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = health_context
    token, device_id = await linked(services)
    async with session_factory() as session:
        device = (await session.execute(select(Device))).scalar_one()
        assert device.token_hash != token
        assert token not in device.token_hash
        assert device.installation_id_hash != "install-1"

    async with session_factory.begin() as session:
        device = (await session.execute(select(Device))).scalar_one()
        device.token_scope = DeviceScope.STATUS_ONLY
    with pytest.raises(HealthConnectError) as invalid_scope:
        await services.health_connect.status(token)
    assert invalid_scope.value.code == "INVALID_SCOPE"

    async with session_factory.begin() as session:
        device = (await session.execute(select(Device))).scalar_one()
        device.token_scope = DeviceScope.HEALTH_CONNECT_SYNC
    devices = await services.health_connect.devices_for_user(42)
    assert devices[0].device_id == device_id
    await services.health_connect.revoke_for_user(42, device_id)
    with pytest.raises(HealthConnectError) as revoked:
        await services.health_connect.sync(token, (run(),), "cursor")
    assert revoked.value.code == "TOKEN_REVOKED"


@pytest.mark.asyncio
async def test_auth_and_batch_validation_create_no_activity(
    health_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = health_context
    token, _ = await linked(services)
    with pytest.raises(HealthConnectError) as invalid_token:
        await services.health_connect.sync("bad-token", (run(),), None)
    assert invalid_token.value.code == "INVALID_TOKEN"
    with pytest.raises(HealthConnectError) as oversized:
        await services.health_connect.sync(token, (run("1"), run("2"), run("3")), None)
    assert oversized.value.code == "BATCH_TOO_LARGE"
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Activity.id))) == 0


@pytest.mark.asyncio
async def test_partial_batch_duplicate_optional_records_and_private_series(
    health_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = health_context
    token, _ = await linked(services)
    samples = (
        HealthConnectSample(
            timestamp=datetime(2026, 7, 6, 6, tzinfo=UTC),
            latitude=55.75,
            longitude=37.61,
            elevation_m=170.0,
            heart_rate=150,
            speed_mps=3.1,
            cadence_spm=170.0,
        ),
    )
    result = await services.health_connect.sync(
        token,
        (run("saved", samples=samples), run("invalid", distance_m=-1)),
        "cursor-partial",
    )
    assert [item.external_id for item in result.items] == ["invalid", "saved"]
    assert [item.state for item in result.items] == [SyncItemState.ERROR, SyncItemState.SAVED]
    assert result.saved_count == 1
    assert result.error_count == 1
    assert result.cursor is None

    duplicate = await services.health_connect.sync(token, (run("saved", samples=samples),), "c2")
    assert duplicate.items[0].state == SyncItemState.DUPLICATE
    optional = await services.health_connect.sync(token, (run("without-optionals"),), "c3")
    assert optional.items[0].state == SyncItemState.SAVED

    async with session_factory() as session:
        activities = (
            (await session.execute(select(Activity).order_by(Activity.external_id))).scalars().all()
        )
        assert len(activities) == 2
        assert all(activity.visibility == ActivityVisibility.PRIVATE for activity in activities)
        assert all(activity.source_type == SourceType.HEALTH_CONNECT for activity in activities)
        assert await session.scalar(select(func.count(CoachReport.id))) == 2
        assert await session.scalar(select(func.count(TelegramOutbox.id))) == 3
        assert await session.scalar(select(func.count(HealthConnectSyncBatch.id))) == 1
        series = (await session.execute(select(ActivitySeries))).scalar_one()
        outbox = (await session.execute(select(TelegramOutbox).limit(1))).scalar_one()
        assert "150" not in outbox.message_text
        assert "55.75" not in outbox.message_text
    payload = json.loads(gzip.decompress(await services.imports.storage.read(series.storage_uri)))
    assert payload[0]["heart_rate"] == 150
    assert payload[0]["latitude"] == 55.75

    await services.groups.setup_group(42, -1001234567890, "Idaten", actor_is_admin=True)
    await services.groups.set_share_level(42, -1001234567890, ShareLevel.DETAILED)
    with pytest.raises(GroupError, match="Privacy"):
        await services.groups.grant_and_prepare_publication(42, -1001234567890, activities[0].id)
    assert await services.groups.leaderboard(-1001234567890) == ()
    async with session_factory() as session:
        still_private = await session.get(Activity, activities[0].id)
        assert still_private is not None
        assert still_private.visibility == ActivityVisibility.PRIVATE


@pytest.mark.asyncio
async def test_outbox_retry_and_delivery_are_idempotent(
    health_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = health_context
    token, _ = await linked(services)
    bootstrap_outbox = TelegramOutboxService(session_factory, retry_seconds=0, max_attempts=3)

    async def bootstrap_send(chat_id: int, message: str) -> int:
        assert chat_id == 42
        assert "Устройство подключено" in message
        return 100

    assert await bootstrap_outbox.deliver_pending(bootstrap_send) == 1
    await services.health_connect.sync(token, (run(),), "cursor")
    outbox = TelegramOutboxService(session_factory, retry_seconds=0, max_attempts=3)
    attempts = 0

    async def flaky_send(chat_id: int, message: str) -> int:
        nonlocal attempts
        attempts += 1
        assert chat_id == 42
        assert message
        if attempts == 1:
            raise RuntimeError("temporary")
        return 777

    assert await outbox.deliver_pending(flaky_send) == 0
    assert await outbox.deliver_pending(flaky_send) == 1
    assert await outbox.deliver_pending(flaky_send) == 0
    assert attempts == 2
    async with session_factory() as session:
        record = (
            await session.execute(
                select(TelegramOutbox).where(TelegramOutbox.activity_id.is_not(None))
            )
        ).scalar_one()
        assert record.status == OutboxStatus.DELIVERED
        assert record.attempts == 2
        assert record.telegram_message_id == 777
        assert await session.scalar(select(func.count(Activity.id))) == 1


@pytest.mark.asyncio
async def test_multi_sync_is_chronological_and_summary_is_idempotent(
    health_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = health_context
    token, _ = await linked(services)
    newer = run("newer")
    older = HealthConnectRun(
        external_id="older",
        started_at=datetime(2026, 7, 5, 6, tzinfo=UTC),
        timezone="Europe/Moscow",
        distance_m=5_000,
        elapsed_time_sec=1_800,
    )

    first = await services.health_connect.sync(token, (newer, older), None, batch_id="delivery-1")
    second = await services.health_connect.sync(token, (older, newer), None, batch_id="delivery-1")

    assert [item.external_id for item in first.items] == ["older", "newer"]
    assert all(item.state == SyncItemState.SAVED for item in first.items)
    assert all(item.state == SyncItemState.DUPLICATE for item in second.items)
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Activity.id))) == 2
        assert await session.scalar(select(func.count(HealthConnectSyncBatch.id))) == 1
        batch_outboxes = await session.scalar(
            select(func.count(TelegramOutbox.id)).where(TelegramOutbox.batch_id.is_not(None))
        )
        assert batch_outboxes == 1
