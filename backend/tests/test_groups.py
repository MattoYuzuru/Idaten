import uuid
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
from app.groups.models import ActivityShareGrant, GroupMember, GroupPublication, ShareLevel
from app.groups.schemas import GroupError, PrivacyGroupAction, PublicationDraft
from app.services import AppServices, build_services
from app.users.schemas import TelegramIdentity

GROUP_CHAT_ID = -1_001_234_567_890
NOW = datetime(2026, 7, 8, 15, tzinfo=UTC)


@pytest.fixture
async def group_context() -> AsyncIterator[tuple[AppServices, async_sessionmaker[AsyncSession]]]:
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


def identity(user_id: int = 42) -> TelegramIdentity:
    return TelegramIdentity(
        telegram_user_id=user_id,
        private_chat_id=user_id,
        username=f"runner{user_id}",
        first_name=f"Runner {user_id}",
    )


async def setup_group(services: AppServices) -> None:
    await services.users.register(identity())
    await services.groups.setup_group(
        42,
        GROUP_CHAT_ID,
        "Idaten Runners",
        actor_is_admin=True,
    )


async def record_run(
    services: AppServices,
    *,
    user_id: int = 42,
    started_at: datetime = NOW,
    distance_m: int = 5_000,
) -> Activity:
    result = await services.activities.record_manual_run(
        identity(user_id), ManualRunInput(distance_m, 1_800, started_at)
    )
    async with services.groups.session_factory() as session:
        activity = await session.get(Activity, result.activity.activity_id)
        assert activity is not None
        session.expunge(activity)
        return activity


async def eligible_draft(services: AppServices, *, user_id: int = 42) -> PublicationDraft:
    activity = await record_run(services, user_id=user_id)
    return await services.groups.grant_and_prepare_publication(user_id, GROUP_CHAT_ID, activity.id)


@pytest.mark.asyncio
async def test_group_setup_is_idempotent_and_join_defaults_to_no_sharing(
    group_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = group_context
    await setup_group(services)
    await services.groups.setup_group(42, GROUP_CHAT_ID, "Idaten Runners", actor_is_admin=True)
    await services.users.register(identity(43))
    member = await services.groups.join(43, GROUP_CHAT_ID)

    assert member.share_level == ShareLevel.NONE
    assert not member.auto_share
    overview = await services.groups.privacy_overview(43)
    assert not overview.group_sharing_enabled

    async with session_factory() as session:
        memberships = await session.scalar(select(func.count(GroupMember.id)))
    assert memberships == 2


@pytest.mark.asyncio
async def test_interactive_privacy_is_idempotent_and_rechecks_membership(
    group_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, _session_factory = group_context
    await setup_group(services)
    group_id = (await services.groups.privacy_overview(42)).groups[0].group_id

    detailed = await services.groups.set_group_privacy(42, group_id, PrivacyGroupAction.DETAILED)
    repeated = await services.groups.set_group_privacy(42, group_id, PrivacyGroupAction.DETAILED)
    always = await services.groups.set_group_privacy(42, group_id, PrivacyGroupAction.ALWAYS)
    disabled = await services.groups.set_privacy(42, enabled=False)
    none = await services.groups.set_group_privacy(42, group_id, PrivacyGroupAction.NONE)

    assert detailed.groups[0].share_level == ShareLevel.DETAILED
    assert repeated == detailed
    assert always.groups[0].auto_share
    assert not disabled.group_sharing_enabled
    assert not disabled.groups[0].auto_share
    assert none.groups[0].share_level == ShareLevel.NONE
    assert not none.groups[0].auto_share

    await services.users.register(identity(43))
    with pytest.raises(GroupError, match="присоедин"):
        await services.groups.set_group_privacy(43, group_id, PrivacyGroupAction.SUMMARY)
    with pytest.raises(GroupError, match="не найдена"):
        await services.groups.set_group_privacy(42, uuid.uuid4(), PrivacyGroupAction.SUMMARY)


@pytest.mark.asyncio
async def test_setup_requires_telegram_admin(
    group_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, _session_factory = group_context
    await services.users.register(identity())

    with pytest.raises(GroupError, match="администратор"):
        await services.groups.setup_group(42, GROUP_CHAT_ID, "Idaten Runners", actor_is_admin=False)


@pytest.mark.asyncio
async def test_private_activity_without_opt_in_is_never_published_or_ranked(
    group_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = group_context
    await setup_group(services)
    activity = await record_run(services)

    assert activity.visibility == ActivityVisibility.PRIVATE
    assert await services.groups.leaderboard(GROUP_CHAT_ID, NOW) == ()

    async with session_factory() as session:
        grants = await session.scalar(select(func.count(ActivityShareGrant.id)))
        publications = await session.scalar(select(func.count(GroupPublication.id)))
    assert grants == 0
    assert publications == 0


@pytest.mark.asyncio
async def test_forged_publication_draft_is_rejected_without_grant(
    group_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = group_context
    await setup_group(services)
    activity = await record_run(services)
    overview = await services.groups.privacy_overview(42)
    group = overview.groups[0]
    async with session_factory() as session:
        member = (await session.execute(select(GroupMember))).scalar_one()

    forged = PublicationDraft(
        group_id=member.group_id,
        telegram_chat_id=group.telegram_chat_id,
        activity_id=activity.id,
        user_id=member.user_id,
        share_level=ShareLevel.SUMMARY,
        message_text="forged",
    )
    with pytest.raises(GroupError, match="Резерв"):
        await services.groups.record_publication(forged, 100)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    [
        "privacy_off",
        "share_none",
        "private",
        "revoked",
        "strava",
        "text",
        "screenshot",
        "deleted",
    ],
)
async def test_privacy_failures_block_publication_and_leaderboard(
    group_context: tuple[AppServices, async_sessionmaker[AsyncSession]], scenario: str
) -> None:
    services, session_factory = group_context
    await setup_group(services)
    draft = await eligible_draft(services)

    if scenario == "privacy_off":
        await services.groups.set_privacy(42, enabled=False)
    elif scenario == "share_none":
        await services.groups.set_share_level(42, GROUP_CHAT_ID, ShareLevel.NONE)
    elif scenario == "revoked":
        await services.groups.decline_publication(42, GROUP_CHAT_ID, draft.activity_id)
    else:
        async with session_factory.begin() as session:
            activity = await session.get(Activity, draft.activity_id)
            assert activity is not None
            if scenario == "private":
                activity.visibility = ActivityVisibility.PRIVATE
            elif scenario == "strava":
                activity.source_type = SourceType.STRAVA
            elif scenario == "text":
                activity.source_type = SourceType.TEXT
            elif scenario == "screenshot":
                activity.source_type = SourceType.SCREENSHOT
            elif scenario == "deleted":
                activity.deleted_at = NOW

    expected_error = "Резерв" if scenario == "revoked" else "Privacy"
    with pytest.raises(GroupError, match=expected_error):
        await services.groups.record_publication(draft, 101)
    assert await services.groups.leaderboard(GROUP_CHAT_ID, NOW) == ()
    assert (await services.groups.week(GROUP_CHAT_ID, NOW)).run_count == 0
    assert await services.groups.streaks(GROUP_CHAT_ID, NOW) == ()


@pytest.mark.asyncio
async def test_left_member_is_ineligible(
    group_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, _session_factory = group_context
    await setup_group(services)
    await services.users.register(identity(43))
    await services.groups.join(43, GROUP_CHAT_ID)
    draft = await eligible_draft(services, user_id=43)

    await services.groups.leave(43, GROUP_CHAT_ID)

    with pytest.raises(GroupError, match="Privacy"):
        await services.groups.record_publication(draft, 102)
    assert await services.groups.leaderboard(GROUP_CHAT_ID, NOW) == ()


@pytest.mark.asyncio
async def test_publication_is_audited_and_repeat_is_rejected(
    group_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = group_context
    await setup_group(services)
    draft = await eligible_draft(services)

    assert await services.groups.record_publication(draft, 777)
    with pytest.raises(GroupError, match="уже опубликована"):
        await services.groups.grant_and_prepare_publication(42, GROUP_CHAT_ID, draft.activity_id)

    async with session_factory() as session:
        publication = (await session.execute(select(GroupPublication))).scalar_one()
    assert publication.telegram_message_id == 777
    assert publication.message_text == draft.message_text


@pytest.mark.asyncio
async def test_cancelled_pending_publication_can_be_retried(
    group_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, _session_factory = group_context
    await setup_group(services)
    draft = await eligible_draft(services)

    await services.groups.cancel_pending_publication(draft)
    retry = await services.groups.grant_and_prepare_publication(
        42, GROUP_CHAT_ID, draft.activity_id
    )

    assert retry.activity_id == draft.activity_id


@pytest.mark.asyncio
async def test_leaderboard_week_and_weekly_streak_are_deterministic(
    group_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, _session_factory = group_context
    await setup_group(services)
    distances = (5_000, 6_000, 7_000)
    for weeks_ago, distance in enumerate(distances):
        activity = await record_run(
            services,
            started_at=NOW - timedelta(weeks=weeks_ago),
            distance_m=distance,
        )
        await services.groups.grant_and_prepare_publication(
            42, GROUP_CHAT_ID, activity.id, always=weeks_ago == 0
        )

    leaderboard = await services.groups.leaderboard(GROUP_CHAT_ID, NOW)
    week = await services.groups.week(GROUP_CHAT_ID, NOW)
    streaks = await services.groups.streaks(GROUP_CHAT_ID, NOW)

    assert [(entry.distance_m, entry.run_count) for entry in leaderboard] == [(5_000, 1)]
    assert (week.distance_m, week.run_count, week.members) == (5_000, 1, 1)
    assert [(entry.display_name, entry.weeks) for entry in streaks] == [("Runner 42", 3)]
