from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.activities.service import ActivityService
from app.core.config import Settings
from app.groups.service import GroupService
from app.ingestion.service import ImportService
from app.storage.service import LocalFilesystemStorage
from app.users.service import UserService


@dataclass(frozen=True, slots=True)
class AppServices:
    users: UserService
    activities: ActivityService
    groups: GroupService
    imports: ImportService


def build_services(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> AppServices:
    users = UserService(
        session_factory=session_factory,
        default_timezone=settings.default_timezone,
        default_locale=settings.default_locale,
    )
    storage = LocalFilesystemStorage(settings.storage_path)
    return AppServices(
        users=users,
        activities=ActivityService(session_factory, users),
        groups=GroupService(session_factory),
        imports=ImportService(
            session_factory,
            users,
            storage,
            max_upload_bytes=settings.max_upload_bytes,
            max_archive_uncompressed_bytes=settings.max_archive_uncompressed_bytes,
            max_archive_entries=settings.max_archive_entries,
            max_archive_ratio=settings.max_archive_ratio,
        ),
    )
