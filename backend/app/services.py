from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.activities.service import ActivityService
from app.core.config import Settings
from app.users.service import UserService


@dataclass(frozen=True, slots=True)
class AppServices:
    users: UserService
    activities: ActivityService


def build_services(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> AppServices:
    users = UserService(
        session_factory=session_factory,
        default_timezone=settings.default_timezone,
        default_locale=settings.default_locale,
    )
    return AppServices(users=users, activities=ActivityService(session_factory, users))
