import uuid
from collections import defaultdict
from datetime import UTC, datetime
from html import escape

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.activities.models import Activity, ActivityVisibility, SourceType
from app.analytics.metrics import format_duration, format_pace, local_week_bounds
from app.groups.models import (
    ActivityShareGrant,
    GroupMember,
    GroupPublication,
    GroupRole,
    PrivacySettings,
    RunningGroup,
    ShareLevel,
)
from app.groups.repository import GroupRepository
from app.groups.schemas import (
    GroupError,
    GroupInfo,
    GroupWeek,
    LeaderboardEntry,
    PrivacyOverview,
    PublicationDraft,
    ShareTarget,
    StreakEntry,
)
from app.groups.streaks import consecutive_week_streak
from app.users.models import User
from app.users.repository import UserRepository


class GroupService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def setup_group(
        self,
        telegram_user_id: int,
        telegram_chat_id: int,
        title: str,
        *,
        actor_is_admin: bool,
    ) -> GroupInfo:
        if not actor_is_admin:
            raise GroupError("Настроить группу может только администратор Telegram-чата.")
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            repository = GroupRepository(session)
            group = await repository.get_group_by_chat_id(telegram_chat_id)
            member: GroupMember
            if group is None:
                group = RunningGroup(
                    telegram_chat_id=telegram_chat_id,
                    title=title,
                    timezone=user.timezone,
                    created_by_user_id=user.id,
                )
                repository.add(group)
                await session.flush()
                member = GroupMember(
                    group_id=group.id,
                    user_id=user.id,
                    role=GroupRole.OWNER,
                    share_level=ShareLevel.NONE,
                )
                repository.add(member)
            else:
                existing_member = await repository.get_member(group.id, user.id)
                if existing_member is None:
                    member = GroupMember(
                        group_id=group.id,
                        user_id=user.id,
                        role=GroupRole.ADMIN,
                        share_level=ShareLevel.NONE,
                    )
                    repository.add(member)
                else:
                    member = existing_member
                if member.left_at is not None:
                    member.left_at = None
                    member.role = GroupRole.ADMIN
            await self._ensure_privacy(repository, user.id)
            return self._group_info(group, member)

    async def join(self, telegram_user_id: int, telegram_chat_id: int) -> GroupInfo:
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            repository = GroupRepository(session)
            group = await self._require_group(repository, telegram_chat_id)
            member = await repository.get_member(group.id, user.id)
            if member is None:
                member = GroupMember(
                    group_id=group.id,
                    user_id=user.id,
                    role=GroupRole.MEMBER,
                    share_level=ShareLevel.NONE,
                )
                repository.add(member)
            elif member.left_at is not None:
                member.left_at = None
                member.share_level = ShareLevel.NONE
                member.auto_share = False
            await self._ensure_privacy(repository, user.id)
            return self._group_info(group, member)

    async def leave(self, telegram_user_id: int, telegram_chat_id: int) -> None:
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            repository = GroupRepository(session)
            group = await self._require_group(repository, telegram_chat_id)
            member = await self._require_active_member(repository, group.id, user.id)
            if member.role == GroupRole.OWNER:
                raise GroupError("Владелец не может выйти, пока роль OWNER не передана.")
            member.left_at = datetime.now(UTC)
            member.share_level = ShareLevel.NONE
            member.auto_share = False

    async def privacy_overview(self, telegram_user_id: int) -> PrivacyOverview:
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            repository = GroupRepository(session)
            privacy = await self._ensure_privacy(repository, user.id)
            memberships = await repository.active_memberships(user.id)
            return PrivacyOverview(
                group_sharing_enabled=privacy.group_sharing_enabled,
                groups=tuple(self._group_info(group, member) for member, group in memberships),
            )

    async def set_privacy(self, telegram_user_id: int, *, enabled: bool) -> PrivacyOverview:
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            repository = GroupRepository(session)
            privacy = await self._ensure_privacy(repository, user.id)
            privacy.group_sharing_enabled = enabled
            memberships = await repository.active_memberships(user.id)
            if not enabled:
                for member, _group in memberships:
                    member.auto_share = False
            return PrivacyOverview(
                group_sharing_enabled=privacy.group_sharing_enabled,
                groups=tuple(self._group_info(group, member) for member, group in memberships),
            )

    async def set_share_level(
        self, telegram_user_id: int, telegram_chat_id: int, share_level: ShareLevel
    ) -> GroupInfo:
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            repository = GroupRepository(session)
            group = await self._require_group(repository, telegram_chat_id)
            member = await self._require_active_member(repository, group.id, user.id)
            privacy = await self._ensure_privacy(repository, user.id)
            member.share_level = share_level
            if share_level == ShareLevel.NONE:
                member.auto_share = False
            else:
                privacy.group_sharing_enabled = True
            return self._group_info(group, member)

    async def share_targets(
        self, telegram_user_id: int, activity_id: uuid.UUID
    ) -> tuple[ShareTarget, ...]:
        async with self.session_factory() as session:
            user = await self._require_user(session, telegram_user_id)
            repository = GroupRepository(session)
            activity = await repository.get_activity_for_user(activity_id, user.id)
            if activity is None:
                raise GroupError("Пробежка не найдена.")
            memberships = await repository.active_memberships(user.id)
            return tuple(
                ShareTarget(group.telegram_chat_id, group.title, member.auto_share)
                for member, group in memberships
            )

    async def grant_and_prepare_publication(
        self,
        telegram_user_id: int,
        telegram_chat_id: int,
        activity_id: uuid.UUID,
        *,
        always: bool = False,
    ) -> PublicationDraft:
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            repository = GroupRepository(session)
            group = await self._require_group(repository, telegram_chat_id)
            member = await self._require_active_member(repository, group.id, user.id)
            activity = await repository.get_activity_for_user(activity_id, user.id)
            if activity is None:
                raise GroupError("Пробежка не найдена.")
            if await repository.get_publication(group.id, activity.id) is not None:
                raise GroupError("Эта пробежка уже опубликована в группе.")

            privacy = await self._ensure_privacy(repository, user.id)
            privacy.group_sharing_enabled = True
            if member.share_level == ShareLevel.NONE:
                member.share_level = ShareLevel.SUMMARY
            if always:
                member.auto_share = True

            grant = await repository.get_grant(group.id, activity.id)
            if grant is None:
                grant = ActivityShareGrant(
                    group_id=group.id,
                    activity_id=activity.id,
                    user_id=user.id,
                    share_level=member.share_level,
                    granted_at=datetime.now(UTC),
                )
                repository.add(grant)
            else:
                grant.share_level = member.share_level
                grant.revoked_at = None
                grant.granted_at = datetime.now(UTC)
            activity.visibility = self._visibility(member.share_level)
            await session.flush()
            self._check_publication_eligibility(activity, member, privacy, grant)
            draft = self._publication_draft(group, user, activity, grant.share_level)
            repository.add(
                GroupPublication(
                    group_id=group.id,
                    activity_id=activity.id,
                    user_id=user.id,
                    telegram_message_id=None,
                    share_level=grant.share_level,
                    message_text=draft.message_text,
                    created_at=datetime.now(UTC),
                )
            )
            return draft

    async def decline_publication(
        self, telegram_user_id: int, telegram_chat_id: int, activity_id: uuid.UUID
    ) -> None:
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            repository = GroupRepository(session)
            group = await self._require_group(repository, telegram_chat_id)
            await self._require_active_member(repository, group.id, user.id)
            activity = await repository.get_activity_for_user(activity_id, user.id)
            if activity is None:
                raise GroupError("Пробежка не найдена.")
            grant = await repository.get_grant(group.id, activity.id)
            publication = await repository.get_publication(group.id, activity.id)
            if grant is not None and (
                publication is None or publication.telegram_message_id is None
            ):
                grant.revoked_at = datetime.now(UTC)
                if publication is not None:
                    await session.delete(publication)

    async def record_publication(self, draft: PublicationDraft, telegram_message_id: int) -> bool:
        async with self.session_factory.begin() as session:
            repository = GroupRepository(session)
            group = await repository.get_group_by_chat_id(draft.telegram_chat_id)
            if group is None or group.id != draft.group_id:
                raise GroupError("Группа не найдена.")
            publication = await repository.get_publication(group.id, draft.activity_id)
            if publication is None:
                raise GroupError("Резерв публикации не найден.")
            if publication.telegram_message_id is not None:
                return False
            activity = await repository.get_activity_for_user(draft.activity_id, draft.user_id)
            member = await repository.get_member(group.id, draft.user_id)
            privacy = await repository.get_privacy(draft.user_id)
            grant = await repository.get_grant(group.id, draft.activity_id)
            if activity is None or member is None or privacy is None or grant is None:
                raise GroupError("Разрешение на публикацию недействительно.")
            self._check_publication_eligibility(activity, member, privacy, grant)
            if (
                publication.user_id != draft.user_id
                or publication.message_text != draft.message_text
                or publication.share_level != draft.share_level
            ):
                raise GroupError("Резерв публикации не соответствует запросу.")
            publication.telegram_message_id = telegram_message_id
            return True

    async def cancel_pending_publication(self, draft: PublicationDraft) -> None:
        async with self.session_factory.begin() as session:
            repository = GroupRepository(session)
            publication = await repository.get_publication(draft.group_id, draft.activity_id)
            if publication is not None and publication.telegram_message_id is None:
                await session.delete(publication)

    async def leaderboard(
        self, telegram_chat_id: int, moment: datetime | None = None
    ) -> tuple[LeaderboardEntry, ...]:
        group, rows = await self._weekly_eligible(telegram_chat_id, moment)
        totals: dict[uuid.UUID, list[int]] = defaultdict(lambda: [0, 0])
        names: dict[uuid.UUID, str] = {}
        for activity, user in rows:
            totals[user.id][0] += activity.distance_m
            totals[user.id][1] += 1
            names[user.id] = user.display_name
        del group
        entries = [
            LeaderboardEntry(names[user_id], values[0], values[1])
            for user_id, values in totals.items()
        ]
        return tuple(sorted(entries, key=lambda item: (-item.distance_m, item.display_name)))

    async def week(self, telegram_chat_id: int, moment: datetime | None = None) -> GroupWeek:
        _group, rows = await self._weekly_eligible(telegram_chat_id, moment)
        return GroupWeek(
            distance_m=sum(activity.distance_m for activity, _user in rows),
            run_count=len(rows),
            members=len({user.id for _activity, user in rows}),
        )

    async def streaks(
        self, telegram_chat_id: int, moment: datetime | None = None
    ) -> tuple[StreakEntry, ...]:
        async with self.session_factory() as session:
            repository = GroupRepository(session)
            group = await self._require_group(repository, telegram_chat_id)
            rows = await repository.eligible_activities(group.id)
        by_user: dict[uuid.UUID, list[datetime]] = defaultdict(list)
        names: dict[uuid.UUID, str] = {}
        for activity, user in rows:
            by_user[user.id].append(activity.started_at)
            names[user.id] = user.display_name
        now = moment or datetime.now(UTC)
        result = [
            StreakEntry(names[user_id], consecutive_week_streak(times, group.timezone, now))
            for user_id, times in by_user.items()
        ]
        return tuple(sorted(result, key=lambda item: (-item.weeks, item.display_name)))

    async def _weekly_eligible(
        self, telegram_chat_id: int, moment: datetime | None
    ) -> tuple[RunningGroup, list[tuple[Activity, User]]]:
        async with self.session_factory() as session:
            repository = GroupRepository(session)
            group = await self._require_group(repository, telegram_chat_id)
            start, end = local_week_bounds(moment or datetime.now(UTC), group.timezone)
            rows = await repository.eligible_activities(
                group.id, started_from=start, started_before=end
            )
            return group, rows

    @staticmethod
    async def _require_user(session: AsyncSession, telegram_user_id: int) -> User:
        found = await UserRepository(session).get_by_telegram_id(telegram_user_id)
        if found is None:
            raise GroupError("Сначала откройте личный чат с ботом и выполните /start.")
        return found[0]

    @staticmethod
    async def _require_group(repository: GroupRepository, telegram_chat_id: int) -> RunningGroup:
        group = await repository.get_group_by_chat_id(telegram_chat_id)
        if group is None:
            raise GroupError("Группа не настроена. Администратор должен выполнить /setup_group.")
        return group

    @staticmethod
    async def _require_active_member(
        repository: GroupRepository, group_id: uuid.UUID, user_id: uuid.UUID
    ) -> GroupMember:
        member = await repository.get_member(group_id, user_id)
        if member is None or member.left_at is not None:
            raise GroupError("Сначала присоединитесь к группе командой /join.")
        return member

    @staticmethod
    async def _ensure_privacy(repository: GroupRepository, user_id: uuid.UUID) -> PrivacySettings:
        settings = await repository.get_privacy(user_id)
        if settings is None:
            settings = PrivacySettings(user_id=user_id, group_sharing_enabled=False)
            repository.add(settings)
        return settings

    @staticmethod
    def _group_info(group: RunningGroup, member: GroupMember) -> GroupInfo:
        return GroupInfo(
            telegram_chat_id=group.telegram_chat_id,
            title=group.title,
            timezone=group.timezone,
            role=member.role,
            share_level=member.share_level,
            auto_share=member.auto_share,
        )

    @staticmethod
    def _visibility(share_level: ShareLevel) -> ActivityVisibility:
        if share_level == ShareLevel.DETAILED:
            return ActivityVisibility.GROUP_DETAILED
        return ActivityVisibility.GROUP_SUMMARY

    @staticmethod
    def _check_publication_eligibility(
        activity: Activity,
        member: GroupMember,
        privacy: PrivacySettings,
        grant: ActivityShareGrant,
    ) -> None:
        allowed_visibility = {
            ActivityVisibility.GROUP_SUMMARY,
            ActivityVisibility.GROUP_DETAILED,
        }
        if (
            member.left_at is not None
            or member.share_level == ShareLevel.NONE
            or not privacy.group_sharing_enabled
            or grant.revoked_at is not None
            or grant.share_level == ShareLevel.NONE
            or activity.visibility not in allowed_visibility
            or activity.source_type != SourceType.MANUAL
            or activity.deleted_at is not None
        ):
            raise GroupError("Privacy-настройки запрещают публикацию этой пробежки.")

    @staticmethod
    def _publication_draft(
        group: RunningGroup, user: User, activity: Activity, share_level: ShareLevel
    ) -> PublicationDraft:
        text = (
            f"🏃 {escape(user.display_name)}\n"
            f"{activity.distance_m / 1000:.2f} км · "
            f"{format_duration(activity.elapsed_time_sec)} · "
            f"{format_pace(activity.avg_pace_sec_per_km)}/км"
        )
        return PublicationDraft(
            group_id=group.id,
            telegram_chat_id=group.telegram_chat_id,
            activity_id=activity.id,
            user_id=user.id,
            share_level=share_level,
            message_text=text,
        )
