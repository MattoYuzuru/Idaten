from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.activities.models import Activity, ActivityType, CoachReport
from app.activities.schemas import ManualRunInput, PossibleDuplicateError
from app.analytics.personal import StandardDistance, progress_bounds
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
async def test_progress_windows_and_record_query_filter_non_runs_and_deleted(
    service_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = service_context
    moment = datetime(2026, 7, 8, 12, tzinfo=UTC)
    bounds = progress_bounds(moment, "Europe/Moscow")
    current = await services.activities.record_manual_run(
        identity(), ManualRunInput(4_900, 1_800, bounds.current_28_start)
    )
    await services.activities.record_manual_run(
        identity(), ManualRunInput(9_800, 3_700, bounds.current_28_start - timedelta(seconds=1))
    )
    half = await services.activities.record_manual_run(
        identity(), ManualRunInput(21_097, 7_800, bounds.previous_28_start - timedelta(days=1))
    )
    deleted = await services.activities.record_manual_run(
        identity(), ManualRunInput(5_000, 1_000, bounds.current_28_start + timedelta(days=1))
    )
    non_run = await services.activities.record_manual_run(
        identity(), ManualRunInput(10_000, 2_000, bounds.current_28_start + timedelta(days=2))
    )
    async with session_factory.begin() as session:
        deleted_activity = await session.get(Activity, deleted.activity.activity_id)
        non_run_activity = await session.get(Activity, non_run.activity.activity_id)
        assert deleted_activity is not None and non_run_activity is not None
        deleted_activity.deleted_at = moment
        non_run_activity.activity_type = ActivityType.BIKE

    progress = await services.activities.stats(42, moment)
    records = await services.activities.personal_records(42)
    by_distance = {item.distance: item for item in records.results}

    assert progress.all_time.run_count == 3
    assert progress.current_28_days.run_count == 1
    assert progress.previous_28_days.run_count == 1
    assert by_distance[StandardDistance.FIVE_K].actual is not None
    assert by_distance[StandardDistance.FIVE_K].actual.activity_id == current.activity.activity_id
    assert by_distance[StandardDistance.TEN_K].actual is not None
    assert by_distance[StandardDistance.HALF_MARATHON].actual is not None
    assert (
        by_distance[StandardDistance.HALF_MARATHON].actual.activity_id == half.activity.activity_id
    )


@pytest.mark.asyncio
async def test_persistent_manual_draft_confirm_is_idempotent(
    service_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = service_context
    draft = await services.activities.start_manual_draft(identity(), datetime.now(UTC))
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


@pytest.mark.asyncio
async def test_manual_duplicate_uses_local_day_and_either_metric(
    service_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = service_context
    first = ManualRunInput(
        10_000,
        3_600,
        datetime(2026, 7, 8, 5, tzinfo=UTC),
        "Europe/Moscow",
    )
    await services.activities.record_manual_run(identity(), first)
    similar_distance = ManualRunInput(
        10_150,
        5_000,
        datetime(2026, 7, 8, 17, tzinfo=UTC),
        "Europe/Moscow",
    )

    with pytest.raises(PossibleDuplicateError) as captured:
        await services.activities.record_manual_run(identity(), similar_distance)

    assert captured.value.candidates[0].distance_matches
    assert not captured.value.candidates[0].duration_matches
    await services.activities.record_manual_run(
        identity(), similar_distance, accept_possible_duplicate=True
    )
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Activity.id))) == 2


@pytest.mark.asyncio
async def test_manual_duplicate_excludes_other_local_day_and_soft_deleted_activity(
    service_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = service_context
    await services.activities.record_manual_run(
        identity(),
        ManualRunInput(
            5_000,
            1_800,
            datetime(2026, 7, 8, 20, 30, tzinfo=UTC),
            "Europe/Moscow",
        ),
    )
    next_local_day = await services.activities.record_manual_run(
        identity(),
        ManualRunInput(
            5_000,
            1_800,
            datetime(2026, 7, 8, 21, 30, tzinfo=UTC),
            "Europe/Moscow",
        ),
    )
    async with session_factory.begin() as session:
        activity = await session.get(Activity, next_local_day.activity.activity_id)
        assert activity is not None
        activity.deleted_at = datetime(2026, 7, 9, tzinfo=UTC)

    saved = await services.activities.record_manual_run(
        identity(),
        ManualRunInput(
            5_100,
            1_900,
            datetime(2026, 7, 9, 5, tzinfo=UTC),
            "Europe/Moscow",
        ),
    )

    assert saved.created
