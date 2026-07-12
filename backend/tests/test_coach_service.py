from collections.abc import AsyncIterator
from datetime import UTC, datetime
from itertools import pairwise

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.activities.models import CoachReport, ReportType
from app.coach.domain import CALCULATOR_VERSION, RULE_VERSION
from app.coach.models import PlannedWorkout, TrainingGoal, TrainingPlan
from app.coach.repository import CoachRepository
from app.core.config import Settings
from app.db.base import Base
from app.services import AppServices, build_services
from app.users.schemas import TelegramIdentity

NOW = datetime(2026, 7, 8, 12, tzinfo=UTC)


@pytest.fixture
async def coach_context() -> AsyncIterator[tuple[AppServices, async_sessionmaker[AsyncSession]]]:
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
    await services.users.register(TelegramIdentity(42, 42, "runner", "Runner"))
    yield services, session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_historical_plan_schema_remains_writable(
    coach_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = coach_context

    plan = await services.coach.create_plan(42, TrainingGoal.FIRST_10K, moment=NOW)

    assert len(plan.workouts) == 4
    async with session_factory() as session:
        stored = await session.get(TrainingPlan, plan.plan_id)
        workouts = tuple(
            (
                await session.scalars(
                    select(PlannedWorkout)
                    .where(PlannedWorkout.plan_id == plan.plan_id)
                    .order_by(PlannedWorkout.week_index)
                )
            ).all()
        )
        report = await session.scalar(
            select(CoachReport).where(CoachReport.report_type == ReportType.PLAN)
        )
    assert stored is not None
    assert stored.calculator_version == CALCULATOR_VERSION
    assert stored.rule_version == RULE_VERSION
    assert report is not None
    targets = report.rule_result_json["weekly_targets_m"]
    assert all(current * 100 <= previous * 110 for previous, current in pairwise(targets))
    assert all(workout.reason and workout.risk_flags is not None for workout in workouts)


@pytest.mark.asyncio
async def test_plan_transaction_failure_leaves_no_partial_plan_or_report(
    coach_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services, session_factory = coach_context
    original = CoachRepository.add_workout
    calls = 0

    def fail_second(repository: CoachRepository, workout: PlannedWorkout) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected transaction failure")
        original(repository, workout)

    monkeypatch.setattr(CoachRepository, "add_workout", fail_second)
    async with session_factory() as session:
        before_reports = int(await session.scalar(select(func.count(CoachReport.id))) or 0)

    with pytest.raises(RuntimeError, match="injected"):
        await services.coach.create_plan(42, TrainingGoal.HALF, moment=NOW)

    async with session_factory() as session:
        assert await session.scalar(select(func.count(TrainingPlan.id))) == 0
        assert await session.scalar(select(func.count(PlannedWorkout.id))) == 0
        assert await session.scalar(select(func.count(CoachReport.id))) == before_reports
