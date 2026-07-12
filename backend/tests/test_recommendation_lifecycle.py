from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.activities.models import CoachReport
from app.activities.schemas import ManualRunInput
from app.coach.models import NextRunRecommendation, RecommendationStatus
from app.coach.schemas import NextFlowState, RecommendationDto
from app.core.config import Settings
from app.db.base import Base
from app.goals.domain import RunningGoalType
from app.readiness.domain import CheckInPhase
from app.readiness.schemas import ReadinessValues
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
    await services.users.register(identity())
    yield services, factory
    await engine.dispose()


def identity() -> TelegramIdentity:
    return TelegramIdentity(42, 42, "runner", "Runner")


def values(
    *,
    readiness: int = 4,
    fatigue: int = 2,
    illness: bool = False,
    available_time_sec: int | None = None,
) -> ReadinessValues:
    return ReadinessValues(
        overall_readiness=readiness,
        general_fatigue=fatigue,
        muscle_soreness=2,
        external_load=2,
        pain_present=False,
        illness_symptoms=illness,
        available_time_sec=available_time_sec,
    )


async def create_recommendation(
    services: AppServices,
    *,
    phase: CheckInPhase = CheckInPhase.POST_RUN,
    moment: datetime = NOW,
    readiness_values: ReadinessValues | None = None,
    key: str = "callback-1",
) -> RecommendationDto:
    draft = await services.next_run.start_check_in(42, phase, moment=moment)
    await services.readiness.update(
        42,
        draft.check_in_id,
        readiness_values or values(),
        expected_version=draft.version,
        moment=moment,
    )
    return await services.next_run.confirm_and_recommend(
        42,
        draft.check_in_id,
        idempotency_key=key,
        moment=moment,
    )


@pytest.mark.asyncio
async def test_flow_requires_goal_then_check_in_and_repeat_is_read_only(
    context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, factory = context
    assert (await services.next_run.state(42, moment=NOW)).state == NextFlowState.NEED_GOAL
    await services.goals.select(42, RunningGoalType.FIRST_5K, moment=NOW)
    assert (
        await services.next_run.state(42, moment=NOW)
    ).state == NextFlowState.NEED_CHECK_IN_METHOD

    first = await create_recommendation(services)
    repeated = await services.next_run.confirm_and_recommend(
        42, first.check_in_id, idempotency_key="callback-1", moment=NOW
    )
    assert first.recommendation_id == repeated.recommendation_id
    async with factory() as session:
        count_before = await session.scalar(select(func.count(NextRunRecommendation.id)))
    await services.next_run.state(42, moment=NOW - timedelta(seconds=1))
    async with factory() as session:
        count_after = await session.scalar(select(func.count(NextRunRecommendation.id)))
    assert count_before == count_after == 1


@pytest.mark.asyncio
async def test_explicit_recalculation_creates_one_idempotent_revision(
    context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, factory = context
    await services.activities.record_manual_run(
        identity(), ManualRunInput(5_000, 1_800, NOW - timedelta(hours=1))
    )
    await services.goals.select(42, RunningGoalType.GENERAL_ENDURANCE, moment=NOW)
    first = await create_recommendation(services)

    recalculated = await services.next_run.recalculate(
        42,
        first.recommendation_id,
        idempotency_key="recalc-callback",
        moment=NOW + timedelta(minutes=1),
    )
    repeated = await services.next_run.recalculate(
        42,
        recalculated.recommendation_id,
        idempotency_key="recalc-callback",
        moment=NOW + timedelta(minutes=2),
    )

    assert repeated.recommendation_id == recalculated.recommendation_id
    async with factory() as session:
        revisions = tuple((await session.scalars(select(NextRunRecommendation))).all())
    assert len(revisions) == 2
    revisions_by_id = {item.id: item for item in revisions}
    assert revisions_by_id[first.recommendation_id].status == RecommendationStatus.SUPERSEDED
    assert (
        revisions_by_id[recalculated.recommendation_id].status == RecommendationStatus.PROVISIONAL
    )
    assert revisions_by_id[recalculated.recommendation_id].supersedes_id == first.recommendation_id


@pytest.mark.asyncio
async def test_pre_run_creates_confirmed_revision_and_respects_provisional_bounds(
    context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, factory = context
    await services.goals.select(42, RunningGoalType.IMPROVE_HALF, target_duration_sec=7_200)
    provisional = await create_recommendation(services)
    state = await services.next_run.state(42, moment=provisional.not_before)
    assert state.state == NextFlowState.NEED_PRE_RUN_CHECK_IN

    confirmed = await create_recommendation(
        services,
        phase=CheckInPhase.PRE_RUN,
        moment=provisional.not_before,
        readiness_values=values(readiness=5, fatigue=0),
        key="pre-run-1",
    )
    async with factory() as session:
        revisions = tuple((await session.scalars(select(NextRunRecommendation))).all())
        reports = {
            report.id: report for report in (await session.scalars(select(CoachReport))).all()
        }
    assert len(revisions) == 2
    revisions_by_id = {item.id: item for item in revisions}
    provisional_revision = revisions_by_id[provisional.recommendation_id]
    confirmed_revision = revisions_by_id[confirmed.recommendation_id]
    assert provisional_revision.status == RecommendationStatus.SUPERSEDED
    assert confirmed_revision.status == RecommendationStatus.CONFIRMED
    assert confirmed_revision.supersedes_id == provisional_revision.id
    provisional_bounds = reports[provisional_revision.report_id].rule_result_json["prescription"][
        "safe_bounds"
    ]
    confirmed_result = reports[confirmed_revision.report_id].rule_result_json["prescription"]
    assert confirmed_result["duration_sec"] <= provisional_bounds["maximum_duration_sec"]
    if confirmed_result["distance_m"] is not None:
        assert confirmed_result["distance_m"] <= provisional_bounds["maximum_distance_m"]
    assert confirmed.status == RecommendationStatus.CONFIRMED.value


@pytest.mark.asyncio
async def test_pre_run_worsening_can_return_rest(
    context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, factory = context
    await services.goals.select(42, RunningGoalType.GENERAL_ENDURANCE)
    provisional = await create_recommendation(services)
    confirmed = await create_recommendation(
        services,
        phase=CheckInPhase.PRE_RUN,
        moment=provisional.not_before,
        readiness_values=values(illness=True),
        key="pre-run-rest",
    )
    async with factory() as session:
        report = await session.get(CoachReport, confirmed.report_id)
    assert report is not None
    assert report.rule_result_json["prescription"]["decision"] == "REST"
    assert "безопаснее не начинать" in confirmed.message


@pytest.mark.asyncio
async def test_new_run_consumes_current_backfill_supersedes_and_retry_is_stable(
    context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, factory = context
    await services.goals.select(42, RunningGoalType.GENERAL_ENDURANCE)
    current = await create_recommendation(services)
    await services.activities.record_manual_run(
        identity(),
        ManualRunInput(5_000, 1_800, datetime.now(UTC) + timedelta(hours=1)),
    )
    async with factory() as session:
        consumed = await session.get(NextRunRecommendation, current.recommendation_id)
        assert consumed is not None and consumed.status == RecommendationStatus.CONSUMED

    second = await create_recommendation(services, moment=NOW + timedelta(days=1), key="second")
    await services.activities.record_manual_run(
        identity(),
        ManualRunInput(6_000, 2_200, NOW - timedelta(days=100)),
    )
    async with factory() as session:
        superseded = await session.get(NextRunRecommendation, second.recommendation_id)
        assert superseded is not None
        assert superseded.status == RecommendationStatus.SUPERSEDED


@pytest.mark.asyncio
async def test_goal_change_and_expiry_close_current_revision(
    context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, factory = context
    await services.goals.select(42, RunningGoalType.FIRST_10K)
    first = await create_recommendation(services)
    await services.goals.select(42, RunningGoalType.FIRST_HALF)
    async with factory() as session:
        changed = await session.get(NextRunRecommendation, first.recommendation_id)
        assert changed is not None and changed.status == RecommendationStatus.SUPERSEDED

    second = await create_recommendation(services, key="after-goal-change")
    state = await services.next_run.state(42, moment=second.valid_until + timedelta(seconds=1))
    assert state.state == NextFlowState.NEED_CHECK_IN_METHOD
    async with factory() as session:
        expired = await session.get(NextRunRecommendation, second.recommendation_id)
        assert expired is not None and expired.status == RecommendationStatus.EXPIRED
