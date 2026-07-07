from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.activities.models import Activity, ActivityVisibility, SourceType
from app.activities.schemas import ManualRunInput
from app.core.config import Settings
from app.db.base import Base
from app.groups.models import (
    GroupMonthlyReport,
    GroupReportOutbox,
    MonthlyOutboxStatus,
    ShareLevel,
)
from app.groups.repository import GroupRepository
from app.services import AppServices, build_services
from app.users.schemas import TelegramIdentity

GROUP_ID = -100_555
JULY = datetime(2026, 7, 10, 8, tzinfo=UTC)
AUGUST = datetime(2026, 8, 2, 8, tzinfo=UTC)


@pytest.fixture
async def monthly_context() -> AsyncIterator[tuple[AppServices, async_sessionmaker[AsyncSession]]]:
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
    await services.users.register(identity(42))
    await services.groups.setup_group(42, GROUP_ID, "Monthly", actor_is_admin=True)
    yield services, session_factory
    await engine.dispose()


def identity(user_id: int) -> TelegramIdentity:
    return TelegramIdentity(
        telegram_user_id=user_id,
        private_chat_id=user_id,
        first_name=f"Runner {user_id}",
    )


async def add_run(
    services: AppServices,
    user_id: int,
    distance_m: int,
    *,
    started_at: datetime = JULY,
    join: bool = True,
) -> Activity:
    await services.users.register(identity(user_id))
    if join and user_id != 42:
        await services.groups.join(user_id, GROUP_ID)
    result = await services.activities.record_manual_run(
        identity(user_id),
        ManualRunInput(distance_m, max(900, distance_m * 360 // 1000), started_at),
    )
    if join:
        await services.groups.grant_and_prepare_publication(
            user_id, GROUP_ID, result.activity.activity_id
        )
    async with services.groups.session_factory() as session:
        activity = await session.get(Activity, result.activity.activity_id)
        assert activity is not None
        session.expunge(activity)
        return activity


@pytest.mark.asyncio
async def test_monthly_awards_use_only_backend_eligible_activities(
    monthly_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = monthly_context
    await add_run(services, 42, 5_000)
    await add_run(services, 43, 7_000)

    privacy_off = await add_run(services, 44, 20_000)
    await services.groups.set_privacy(44, enabled=False)
    none = await add_run(services, 45, 21_000)
    await services.groups.set_share_level(45, GROUP_ID, ShareLevel.NONE)
    private = await add_run(services, 46, 22_000)
    deleted = await add_run(services, 47, 23_000)
    forbidden_source = await add_run(services, 48, 24_000)
    await add_run(services, 49, 25_000, join=False)
    async with session_factory.begin() as session:
        assert await session.get(Activity, privacy_off.id) is not None
        private_row = await session.get(Activity, private.id)
        deleted_row = await session.get(Activity, deleted.id)
        source_row = await session.get(Activity, forbidden_source.id)
        none_row = await session.get(Activity, none.id)
        assert private_row and deleted_row and source_row and none_row
        private_row.visibility = ActivityVisibility.PRIVATE
        deleted_row.deleted_at = JULY
        source_row.source_type = SourceType.STRAVA

    facts = await services.monthly.current(GROUP_ID, JULY)

    assert facts.distance_m == 12_000
    assert facts.run_count == 2
    assert facts.members == 2
    assert facts.most_distance == "Runner 43"
    assert facts.longest_run == "Runner 43"
    assert facts.consistency == "Runner 42"
    assert facts.pair_runs == 1


@pytest.mark.asyncio
async def test_group_goal_and_monthly_job_outbox_are_idempotent_on_retry(
    monthly_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = monthly_context
    await add_run(services, 42, 5_000)
    facts = await services.monthly.set_goal(GROUP_ID, 100_000, JULY, actor_is_admin=True)
    assert facts.goal_distance_m == 100_000

    assert await services.monthly.generate_previous_month(AUGUST) == 1
    assert await services.monthly.generate_previous_month(AUGUST) == 0
    async with session_factory() as session:
        assert await session.scalar(select(func.count(GroupMonthlyReport.id))) == 1
        assert await session.scalar(select(func.count(GroupReportOutbox.id))) == 1

    attempts = 0

    async def send(_chat_id: int, _message: str) -> int:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("telegram unavailable")
        return 777

    async with session_factory.begin() as session:
        record = await session.scalar(select(GroupReportOutbox))
        assert record is not None
        record.available_at = datetime.now(UTC) - timedelta(seconds=1)
    assert await services.monthly.deliver_pending(send) == 0
    async with session_factory.begin() as session:
        record = await session.scalar(select(GroupReportOutbox))
        assert record is not None
        assert record.status == MonthlyOutboxStatus.PENDING
        record.available_at = datetime.now(UTC) - timedelta(seconds=1)
    assert await services.monthly.deliver_pending(send) == 1
    assert await services.monthly.deliver_pending(send) == 0
    assert attempts == 2
    async with session_factory() as session:
        record = await session.scalar(select(GroupReportOutbox))
        assert record is not None
        assert record.status == MonthlyOutboxStatus.DELIVERED
        assert record.telegram_message_id == 777


@pytest.mark.asyncio
async def test_monthly_transaction_failure_leaves_no_partial_report_or_outbox(
    monthly_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services, session_factory = monthly_context
    await add_run(services, 42, 5_000)
    original = GroupRepository.add

    def fail_outbox(repository: GroupRepository, entity: object) -> None:
        if isinstance(entity, GroupReportOutbox):
            raise RuntimeError("injected monthly failure")
        original(repository, entity)

    monkeypatch.setattr(GroupRepository, "add", fail_outbox)

    with pytest.raises(RuntimeError, match="injected"):
        await services.monthly.generate_previous_month(AUGUST)

    async with session_factory() as session:
        assert await session.scalar(select(func.count(GroupMonthlyReport.id))) == 0
        assert await session.scalar(select(func.count(GroupReportOutbox.id))) == 0
