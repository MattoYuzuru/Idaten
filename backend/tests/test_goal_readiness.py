from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.activities.schemas import ManualRunInput
from app.core.config import Settings
from app.db.base import Base
from app.goals.models import RunningGoal, RunningGoalStatus, RunningGoalType
from app.goals.schemas import GoalError
from app.readiness.models import CheckInPhase, CheckInStatus, ReadinessCheckIn
from app.readiness.schemas import ReadinessError, ReadinessValues
from app.services import AppServices, build_services
from app.users.schemas import TelegramIdentity

NOW = datetime(2026, 7, 12, 12, tzinfo=UTC)


@pytest.fixture
async def context() -> AsyncIterator[tuple[AppServices, async_sessionmaker[AsyncSession]]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    services = build_services(
        factory,
        Settings(database_url="sqlite+aiosqlite://", default_timezone="UTC", _env_file=None),
    )
    await services.users.register(identity(42))
    await services.users.register(identity(43))
    yield services, factory
    await engine.dispose()


def identity(user_id: int) -> TelegramIdentity:
    return TelegramIdentity(user_id, user_id, f"runner{user_id}", "Runner")


def ready_values(
    *,
    motivation: int | None = None,
    sleep_duration_sec: int | None = None,
    session_rpe: int | None = None,
    pain_present: bool = False,
    pain_severity: int | None = None,
) -> ReadinessValues:
    return ReadinessValues(
        overall_readiness=4,
        general_fatigue=2,
        muscle_soreness=1,
        motivation=motivation,
        sleep_duration_sec=sleep_duration_sec,
        external_load=3,
        pain_present=pain_present,
        pain_severity=pain_severity,
        illness_symptoms=False,
        session_rpe=session_rpe,
    )


@pytest.mark.asyncio
async def test_goal_change_preserves_history_and_requires_improvement_time(
    context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, factory = context
    with pytest.raises(GoalError, match="целевое время"):
        await services.goals.select(42, RunningGoalType.IMPROVE_HALF, moment=NOW)

    first = await services.goals.select(42, RunningGoalType.FIRST_5K, moment=NOW)
    second = await services.goals.select(
        42,
        RunningGoalType.IMPROVE_HALF,
        target_duration_sec=7_200,
        moment=NOW + timedelta(seconds=1),
    )
    history = await services.goals.history(42)

    assert first.goal_id != second.goal_id
    assert [item.status for item in history] == [
        RunningGoalStatus.CANCELLED,
        RunningGoalStatus.ACTIVE,
    ]
    async with factory() as session:
        assert (
            await session.scalar(
                select(func.count(RunningGoal.id)).where(
                    RunningGoal.status == RunningGoalStatus.ACTIVE
                )
            )
            == 1
        )


@pytest.mark.asyncio
async def test_goal_completion_is_explicit_and_uses_standard_distance_contract(
    context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, _factory = context
    goal = await services.goals.select(42, RunningGoalType.FIRST_5K, moment=NOW)
    await services.activities.record_manual_run(
        identity(42), ManualRunInput(4_900, 1_900, NOW + timedelta(days=1))
    )

    achievement = await services.goals.achievement(42, moment=NOW + timedelta(days=2))
    assert achievement is not None
    active = await services.goals.active(42)
    assert active is not None and active.status == RunningGoalStatus.ACTIVE

    completed = await services.goals.complete(42, goal.goal_id, moment=NOW + timedelta(days=2))
    assert completed.status == RunningGoalStatus.COMPLETED
    assert await services.goals.active(42) is None


@pytest.mark.asyncio
async def test_time_goal_ignores_long_run_pace_estimate(
    context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, _factory = context
    await services.goals.select(
        42,
        RunningGoalType.IMPROVE_HALF,
        target_duration_sec=7_200,
        moment=NOW,
    )
    await services.activities.record_manual_run(
        identity(42), ManualRunInput(30_000, 9_000, NOW + timedelta(days=1))
    )
    assert await services.goals.achievement(42, moment=NOW + timedelta(days=2)) is None


@pytest.mark.asyncio
async def test_readiness_confirm_is_typed_immutable_and_idempotent(
    context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, factory = context
    draft = await services.readiness.start_draft(42, CheckInPhase.POST_RUN, moment=NOW)
    updated = await services.readiness.update(
        42,
        draft.check_in_id,
        ready_values(motivation=5, sleep_duration_sec=28_800, session_rpe=6),
        expected_version=draft.version,
        moment=NOW,
    )
    confirmed = await services.readiness.confirm(42, draft.check_in_id, moment=NOW)
    repeated = await services.readiness.confirm(42, draft.check_in_id, moment=NOW)

    assert updated.values.motivation == 5
    assert confirmed.status == CheckInStatus.CONFIRMED
    assert repeated == confirmed
    with pytest.raises(ReadinessError, match="нельзя редактировать"):
        await services.readiness.update(42, draft.check_in_id, ready_values(), moment=NOW)
    async with factory() as session:
        assert await session.scalar(select(func.count(ReadinessCheckIn.id))) == 1


@pytest.mark.asyncio
async def test_readiness_required_pain_phase_ownership_and_expiry(
    context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, _factory = context
    draft = await services.readiness.start_draft(42, CheckInPhase.PRE_RUN, moment=NOW)
    assert draft.phase == CheckInPhase.PRE_RUN
    with pytest.raises(ReadinessError, match="Session RPE"):
        await services.readiness.update(
            42,
            draft.check_in_id,
            ready_values(session_rpe=5),
            moment=NOW,
        )
    with pytest.raises(ReadinessError, match="pain details"):
        await services.readiness.update(
            42,
            draft.check_in_id,
            ready_values(pain_present=False, pain_severity=2),
            moment=NOW,
        )
    with pytest.raises(ReadinessError, match="не найден"):
        await services.readiness.get(43, draft.check_in_id)
    with pytest.raises(ReadinessError, match="истёк"):
        await services.readiness.confirm(42, draft.check_in_id, moment=NOW + timedelta(hours=25))
