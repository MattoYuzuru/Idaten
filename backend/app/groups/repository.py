import uuid
from datetime import date, datetime

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.activities.models import Activity, ActivityType, ActivityVisibility, SourceType
from app.groups.models import (
    ActivityShareGrant,
    GroupGoal,
    GroupMember,
    GroupMonthlyReport,
    GroupPublication,
    GroupReportOutbox,
    MonthlyOutboxStatus,
    PrivacySettings,
    RunningGroup,
    ShareLevel,
)
from app.users.models import User


class GroupRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_group_by_chat_id(self, telegram_chat_id: int) -> RunningGroup | None:
        result = await self.session.execute(
            select(RunningGroup).where(RunningGroup.telegram_chat_id == telegram_chat_id)
        )
        return result.scalar_one_or_none()

    async def get_group_by_id(self, group_id: uuid.UUID) -> RunningGroup | None:
        return await self.session.get(RunningGroup, group_id)

    async def groups(self) -> tuple[RunningGroup, ...]:
        return tuple((await self.session.scalars(select(RunningGroup))).all())

    async def goal(self, group_id: uuid.UUID, period_start: date) -> GroupGoal | None:
        result = await self.session.execute(
            select(GroupGoal).where(
                GroupGoal.group_id == group_id, GroupGoal.period_start == period_start
            )
        )
        return result.scalar_one_or_none()

    async def monthly_report(
        self, group_id: uuid.UUID, period_start: date
    ) -> GroupMonthlyReport | None:
        result = await self.session.execute(
            select(GroupMonthlyReport).where(
                GroupMonthlyReport.group_id == group_id,
                GroupMonthlyReport.period_start == period_start,
                GroupMonthlyReport.report_type == "MONTHLY",
            )
        )
        return result.scalar_one_or_none()

    async def pending_monthly_outbox(
        self, now: datetime, *, limit: int
    ) -> tuple[GroupReportOutbox, ...]:
        rows = await self.session.scalars(
            select(GroupReportOutbox)
            .where(
                GroupReportOutbox.available_at <= now,
                or_(
                    GroupReportOutbox.status == MonthlyOutboxStatus.PENDING,
                    (GroupReportOutbox.status == MonthlyOutboxStatus.PROCESSING)
                    & (GroupReportOutbox.lease_expires_at <= now),
                ),
            )
            .order_by(GroupReportOutbox.created_at, GroupReportOutbox.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return tuple(rows)

    async def monthly_outbox(self, record_id: uuid.UUID) -> GroupReportOutbox | None:
        return await self.session.get(GroupReportOutbox, record_id)

    async def monthly_outbox_for_update(self, record_id: uuid.UUID) -> GroupReportOutbox | None:
        return await self.session.get(GroupReportOutbox, record_id, with_for_update=True)

    async def get_member(self, group_id: uuid.UUID, user_id: uuid.UUID) -> GroupMember | None:
        result = await self.session.execute(
            select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def active_memberships(
        self, user_id: uuid.UUID
    ) -> list[tuple[GroupMember, RunningGroup]]:
        rows = await self.session.execute(
            select(GroupMember, RunningGroup)
            .join(RunningGroup, RunningGroup.id == GroupMember.group_id)
            .where(GroupMember.user_id == user_id, GroupMember.left_at.is_(None))
            .order_by(RunningGroup.title)
        )
        return [(row[0], row[1]) for row in rows]

    async def get_privacy(self, user_id: uuid.UUID) -> PrivacySettings | None:
        return await self.session.get(PrivacySettings, user_id)

    async def get_activity_for_user(
        self, activity_id: uuid.UUID, user_id: uuid.UUID
    ) -> Activity | None:
        result = await self.session.execute(
            select(Activity).where(Activity.id == activity_id, Activity.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_grant(
        self, group_id: uuid.UUID, activity_id: uuid.UUID
    ) -> ActivityShareGrant | None:
        result = await self.session.execute(
            select(ActivityShareGrant).where(
                ActivityShareGrant.group_id == group_id,
                ActivityShareGrant.activity_id == activity_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_publication(
        self, group_id: uuid.UUID, activity_id: uuid.UUID
    ) -> GroupPublication | None:
        result = await self.session.execute(
            select(GroupPublication).where(
                GroupPublication.group_id == group_id,
                GroupPublication.activity_id == activity_id,
            )
        )
        return result.scalar_one_or_none()

    async def eligible_activities(
        self,
        group_id: uuid.UUID,
        *,
        started_from: datetime | None = None,
        started_before: datetime | None = None,
    ) -> list[tuple[Activity, User]]:
        statement = self._eligible_statement(group_id)
        if started_from is not None:
            statement = statement.where(Activity.started_at >= started_from)
        if started_before is not None:
            statement = statement.where(Activity.started_at < started_before)
        rows = await self.session.execute(statement.order_by(Activity.started_at))
        return [(row[0], row[1]) for row in rows]

    @staticmethod
    def _eligible_statement(group_id: uuid.UUID) -> Select[tuple[Activity, User]]:
        return (
            select(Activity, User)
            .join(User, User.id == Activity.user_id)
            .join(
                GroupMember,
                (GroupMember.group_id == group_id) & (GroupMember.user_id == Activity.user_id),
            )
            .join(
                PrivacySettings,
                PrivacySettings.user_id == Activity.user_id,
            )
            .join(
                ActivityShareGrant,
                (ActivityShareGrant.group_id == group_id)
                & (ActivityShareGrant.activity_id == Activity.id)
                & (ActivityShareGrant.user_id == Activity.user_id),
            )
            .where(
                GroupMember.left_at.is_(None),
                GroupMember.share_level != ShareLevel.NONE,
                PrivacySettings.group_sharing_enabled.is_(True),
                ActivityShareGrant.revoked_at.is_(None),
                ActivityShareGrant.share_level != ShareLevel.NONE,
                Activity.activity_type == ActivityType.RUN,
                Activity.visibility.in_(
                    (ActivityVisibility.GROUP_SUMMARY, ActivityVisibility.GROUP_DETAILED)
                ),
                Activity.source_type == SourceType.MANUAL,
                Activity.deleted_at.is_(None),
            )
        )

    def add(self, entity: object) -> None:
        self.session.add(entity)
