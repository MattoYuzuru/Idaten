from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.activities.models import Activity, CoachReport
from app.activities.schemas import ManualRunInput
from app.core.config import Settings
from app.db.base import Base
from app.services import AppServices, build_services
from app.users.models import TelegramAccount, User
from app.users.schemas import TelegramIdentity


@pytest.fixture
async def service_context() -> tuple[AppServices, async_sessionmaker[AsyncSession]]:
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
            default_timezone="Europe/Moscow",
            _env_file=None,
        ),
    )
    yield services, session_factory
    await engine.dispose()


def identity() -> TelegramIdentity:
    return TelegramIdentity(
        telegram_user_id=42,
        private_chat_id=42,
        username="runner",
        first_name="Матвей",
    )


@pytest.mark.asyncio
async def test_registration_is_idempotent(
    service_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = service_context
    await services.users.register(identity())
    await services.users.register(identity())

    async with session_factory() as session:
        users = await session.scalar(select(func.count(User.id)))
        accounts = await session.scalar(select(func.count(TelegramAccount.id)))
    assert users == 1
    assert accounts == 1


@pytest.mark.asyncio
async def test_manual_run_updates_stats_week_pr_and_report(
    service_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = service_context
    moment = datetime(2026, 7, 8, 15, tzinfo=UTC)

    result = await services.activities.record_manual_run(
        identity(), ManualRunInput(10_020, 3_761, moment)
    )
    await services.activities.record_manual_run(
        identity(), ManualRunInput(5_000, 1_800, moment - timedelta(days=8))
    )

    assert result.activity.avg_pace_sec_per_km == 375
    assert "<b>10.02 км</b> · 1:02:41 · <b>6:15/км</b>" in result.report_message
    assert "1-я пробежка на неделе 6–12 июля" in result.report_message
    assert result.week_stats.run_count == 1

    stats = await services.activities.stats(42)
    week = await services.activities.week(42, moment)
    records = await services.activities.personal_records(42)

    assert stats.distance_m == 15_020
    assert stats.run_count == 2
    assert week.run_count == 1
    assert records.best_5k is not None
    assert records.best_10k is not None

    async with session_factory() as session:
        activity_count = await session.scalar(select(func.count(Activity.id)))
        report_count = await session.scalar(select(func.count(CoachReport.id)))
    assert activity_count == 2
    assert report_count == 2


@pytest.mark.asyncio
async def test_persistent_manual_draft_confirm_is_idempotent(
    service_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = service_context
    draft = await services.activities.start_manual_draft(
        identity(), datetime(2026, 7, 8, 12, tzinfo=UTC)
    )
    await services.activities.set_manual_draft_field(42, draft.draft_id, "distance", "10.02")
    await services.activities.set_manual_draft_field(42, draft.draft_id, "elapsed", "1:02:41")
    await services.activities.set_manual_draft_field(42, draft.draft_id, "hr", "152")
    await services.activities.set_manual_draft_field(42, draft.draft_id, "max_hr", "178")
    await services.activities.set_manual_draft_field(42, draft.draft_id, "cadence", "171")
    await services.activities.set_manual_draft_field(42, draft.draft_id, "elevation", "164")
    await services.activities.set_manual_draft_field(42, draft.draft_id, "title", "Tempo <private>")

    first = await services.activities.confirm_manual_draft(42, draft.draft_id)
    repeated = await services.activities.confirm_manual_draft(42, draft.draft_id)

    assert repeated.activity.activity_id == first.activity.activity_id
    assert first.created is True
    assert repeated.created is False
    async with session_factory() as session:
        activities = (await session.execute(select(Activity))).scalars().all()
        assert len(activities) == 1
        assert activities[0].avg_hr == 152
        assert activities[0].max_hr == 178
        assert activities[0].avg_cadence_spm == 171
        assert activities[0].elevation_gain_m == 164
        assert activities[0].title == "Tempo <private>"
