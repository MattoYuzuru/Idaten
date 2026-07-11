import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.activities.models import Activity, CoachReport, ReportType, SourceType
from app.activities.schemas import ManualRunInput
from app.coach.domain import CALCULATOR_VERSION, RULE_VERSION
from app.coach.models import PlannedWorkout, TrainingGoal, TrainingPlan
from app.coach.provider import (
    LLMProviderName,
    ProviderExecutor,
)
from app.coach.repository import CoachRepository
from app.coach.service import CoachService
from app.core.config import Settings
from app.db.base import Base
from app.services import AppServices, build_services
from app.users.schemas import TelegramIdentity

NOW = datetime(2026, 7, 8, 12, tzinfo=UTC)


class FakeProvider:
    name = LLMProviderName.OPENAI
    model = "fake-model"

    def __init__(self, *, delay: float = 0, error: bool = False) -> None:
        self.delay = delay
        self.error = error
        self.calls = 0
        self.payloads: list[dict[str, object]] = []

    async def word(self, payload: dict[str, object]) -> str:
        self.calls += 1
        self.payloads.append(payload)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise ValueError("provider failed")
        return "Переформулированная рекомендация"


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
    await services.users.register(identity())
    yield services, session_factory
    await engine.dispose()


def identity() -> TelegramIdentity:
    return TelegramIdentity(42, 42, "runner", "Runner")


async def add_history(services: AppServices, count: int = 4) -> None:
    for index in range(count):
        await services.activities.record_manual_run(
            identity(),
            ManualRunInput(
                5_000 + index * 500,
                1_800 + index * 180,
                NOW - timedelta(days=index * 8) - timedelta(hours=2),
            ),
        )


@pytest.mark.asyncio
async def test_next_without_history_is_safe_and_persists_versions(
    coach_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = coach_context

    result = await services.coach.next_workout(42, NOW)

    assert result.recommendation.distance_m == 3_000
    assert "истории пока мало" in result.recommendation.reason
    assert result.provider == "NONE"
    assert result.recommendation.recommended_on == NOW.date() + timedelta(days=1)
    assert "не раньше" in result.message
    assert "Что учтено" in result.message
    async with session_factory() as session:
        report = await session.get(CoachReport, result.report_id)
        assert report is not None
        assert report.facts_json["calculator_version"] == CALCULATOR_VERSION
        assert report.facts_json["rule_version"] == RULE_VERSION
        assert report.rule_result_json["rule_version"] == RULE_VERSION


@pytest.mark.asyncio
async def test_next_with_history_and_safe_plan_progression(
    coach_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = coach_context
    await add_history(services)

    next_result = await services.coach.next_workout(42, NOW)
    plan = await services.coach.create_plan(42, TrainingGoal.FIRST_10K, moment=NOW)

    assert next_result.recommendation.distance_m >= 4_000
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
async def test_backfilled_run_does_not_replace_latest_completed_workout(
    coach_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, _session_factory = coach_context
    latest = NOW - timedelta(days=1)
    await services.activities.record_manual_run(identity(), ManualRunInput(5_000, 1_800, latest))
    await services.activities.record_manual_run(
        identity(), ManualRunInput(10_000, 3_600, NOW - timedelta(days=90))
    )

    result = await services.coach.next_workout(42, NOW)

    assert result.facts.last_completed_local_date == latest.date()
    assert result.recommendation.recommended_on == NOW.date()


@pytest.mark.asyncio
async def test_template_fallback_without_api_key(
    coach_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, _session_factory = coach_context
    await services.coach.set_external_processing(42, enabled=True)

    result = await services.coach.next_workout(42, NOW)

    assert result.provider == "NONE"
    assert result.message.startswith("<b>Следующая тренировка</b>")


@pytest.mark.asyncio
async def test_external_processing_requires_opt_in_and_payload_is_allowlisted(
    coach_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = coach_context
    await add_history(services)
    provider = FakeProvider()
    coach = CoachService(session_factory, ProviderExecutor(provider, timeout_seconds=1, retries=0))

    first = await coach.next_workout(42, NOW)
    await coach.set_external_processing(42, enabled=True)
    second = await coach.next_workout(42, NOW)

    assert first.provider == "NONE"
    assert provider.calls == 1
    assert second.provider == "OPENAI"
    assert "Дистанция:" in second.message
    assert "Комментарий" in second.message
    payload = json.dumps(provider.payloads[0], sort_keys=True).lower()
    for forbidden in (
        "route",
        "gps",
        "heart",
        "hr",
        "raw",
        "started_at",
        "user",
        "telegram",
        "person",
        "token",
    ):
        assert forbidden not in payload
    async with session_factory() as session:
        report = await session.get(CoachReport, second.report_id)
    assert report is not None
    assert report.provider == "OPENAI"
    assert report.provider_model == "fake-model"
    assert report.prompt_hash is not None and len(report.prompt_hash) == 64


@pytest.mark.asyncio
async def test_strava_history_blocks_external_provider(
    coach_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = coach_context
    await add_history(services, 1)
    async with session_factory.begin() as session:
        activity = await session.scalar(select(Activity))
        assert activity is not None
        activity.source_type = SourceType.STRAVA
    provider = FakeProvider()
    coach = CoachService(session_factory, ProviderExecutor(provider, timeout_seconds=1, retries=0))
    await coach.set_external_processing(42, enabled=True)

    result = await coach.next_workout(42, NOW)

    assert result.provider == "NONE"
    assert provider.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["timeout", "error"])
async def test_provider_timeout_error_retry_and_fallback(
    coach_context: tuple[AppServices, async_sessionmaker[AsyncSession]], mode: str
) -> None:
    _services, session_factory = coach_context
    provider = FakeProvider(delay=0.05 if mode == "timeout" else 0, error=mode == "error")
    coach = CoachService(
        session_factory,
        ProviderExecutor(provider, timeout_seconds=0.001, retries=1),
    )
    await coach.set_external_processing(42, enabled=True)

    result = await coach.next_workout(42, NOW)

    assert provider.calls == 2
    assert result.provider == "NONE"
    assert result.message.startswith("<b>Следующая тренировка</b>")
    async with session_factory() as session:
        assert await session.get(CoachReport, result.report_id) is not None


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
    before_reports: int
    async with session_factory() as session:
        before_reports = int(await session.scalar(select(func.count(CoachReport.id))) or 0)

    with pytest.raises(RuntimeError, match="injected"):
        await services.coach.create_plan(42, TrainingGoal.HALF, moment=NOW)

    async with session_factory() as session:
        assert await session.scalar(select(func.count(TrainingPlan.id))) == 0
        assert await session.scalar(select(func.count(PlannedWorkout.id))) == 0
        assert await session.scalar(select(func.count(CoachReport.id))) == before_reports
