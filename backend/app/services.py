from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.activities.service import ActivityService
from app.core.config import Settings
from app.groups.service import GroupService
from app.health_connect.outbox import TelegramOutboxService
from app.health_connect.service import HealthConnectService
from app.ingestion.service import ImportService
from app.storage.service import LocalFilesystemStorage
from app.users.service import UserService


@dataclass(frozen=True, slots=True)
class AppServices:
    users: UserService
    activities: ActivityService
    groups: GroupService
    imports: ImportService
    health_connect: HealthConnectService
    outbox: TelegramOutboxService


def build_services(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> AppServices:
    users = UserService(
        session_factory=session_factory,
        default_timezone=settings.default_timezone,
        default_locale=settings.default_locale,
    )
    storage = LocalFilesystemStorage(settings.storage_path)
    health_connect = HealthConnectService(
        session_factory,
        users,
        storage,
        security_pepper=settings.device_security_pepper,
        link_ttl_seconds=settings.health_connect_link_ttl_seconds,
        link_attempt_limit=settings.health_connect_link_attempt_limit,
        link_attempt_window_seconds=settings.health_connect_link_attempt_window_seconds,
        max_batch_size=settings.health_connect_max_batch_size,
    )
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
        health_connect=health_connect,
        outbox=TelegramOutboxService(session_factory),
    )
