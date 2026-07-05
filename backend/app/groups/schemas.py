import uuid
from dataclasses import dataclass

from app.groups.models import GroupRole, ShareLevel


class GroupError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class GroupInfo:
    telegram_chat_id: int
    title: str
    timezone: str
    role: GroupRole
    share_level: ShareLevel
    auto_share: bool


@dataclass(frozen=True, slots=True)
class PrivacyOverview:
    group_sharing_enabled: bool
    groups: tuple[GroupInfo, ...]


@dataclass(frozen=True, slots=True)
class ShareTarget:
    telegram_chat_id: int
    title: str
    auto_share: bool


@dataclass(frozen=True, slots=True)
class PublicationDraft:
    group_id: uuid.UUID
    telegram_chat_id: int
    activity_id: uuid.UUID
    user_id: uuid.UUID
    share_level: ShareLevel
    message_text: str


@dataclass(frozen=True, slots=True)
class LeaderboardEntry:
    display_name: str
    distance_m: int
    run_count: int


@dataclass(frozen=True, slots=True)
class GroupWeek:
    distance_m: int
    run_count: int
    members: int


@dataclass(frozen=True, slots=True)
class StreakEntry:
    display_name: str
    weeks: int
