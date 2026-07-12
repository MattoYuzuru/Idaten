from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.activities.service import ActivityService
from app.ai.contracts import AiRoute, AiTask
from app.ai.providers.openai import OpenAiProvider
from app.ai.registry import AiRegistry
from app.ai.router import AiRouter
from app.ai.service import AiReadinessInputService
from app.assisted.service import AssistedActivityService
from app.coach.adaptive_service import NextRunService
from app.coach.lifecycle import RecommendationLifecycle
from app.coach.service import CoachService
from app.core.config import Settings
from app.goals.service import GoalService
from app.groups.monthly_service import MonthlyReportService
from app.groups.service import GroupService
from app.health_connect.outbox import TelegramOutboxService
from app.health_connect.service import HealthConnectService
from app.ingestion.service import ImportService
from app.readiness.service import ReadinessService
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
    coach: CoachService
    monthly: MonthlyReportService
    assisted: AssistedActivityService
    goals: GoalService
    readiness: ReadinessService
    next_run: NextRunService
    ai_readiness: AiReadinessInputService


def build_services(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> AppServices:
    users = UserService(
        session_factory=session_factory,
        default_timezone=settings.default_timezone,
        default_locale=settings.default_locale,
    )
    storage = LocalFilesystemStorage(settings.storage_path)
    recommendation_lifecycle = RecommendationLifecycle()
    health_connect = HealthConnectService(
        session_factory,
        users,
        storage,
        security_pepper=settings.device_security_pepper,
        link_ttl_seconds=settings.health_connect_link_ttl_seconds,
        link_attempt_limit=settings.health_connect_link_attempt_limit,
        link_attempt_window_seconds=settings.health_connect_link_attempt_window_seconds,
        max_batch_size=settings.health_connect_max_batch_size,
        recommendation_lifecycle=recommendation_lifecycle,
    )
    coach = CoachService(session_factory)
    ai_registry = AiRegistry()
    if settings.ai_api_key:
        ai_registry.register(
            OpenAiProvider(
                settings.ai_api_key,
                settings.ai_openai_endpoint,
                request_timeout_seconds=settings.ai_timeout_seconds,
            )
        )
    ai_router = AiRouter(
        ai_registry,
        {
            AiTask.ACTIVITY_EXTRACTION: AiRoute(
                settings.ai_task_activity_extraction_provider.strip()
                or settings.ai_default_provider,
                settings.ai_task_activity_extraction_model,
            ),
            AiTask.READINESS_EXTRACTION: AiRoute(
                settings.ai_task_readiness_extraction_provider.strip()
                or settings.ai_default_provider,
                settings.ai_task_readiness_extraction_model,
            ),
            AiTask.VOICE_TRANSCRIPTION: AiRoute(
                settings.ai_task_voice_transcription_provider.strip()
                or settings.ai_default_provider,
                settings.ai_task_voice_transcription_model,
            ),
        },
        enabled=settings.ai_enabled,
        timeout_seconds=settings.ai_timeout_seconds,
        retries=settings.ai_retries,
    )
    assisted = AssistedActivityService(
        session_factory,
        users,
        ai_router,
        enabled=settings.ai_enabled and settings.bot_owner_telegram_id is not None,
        owner_telegram_user_id=settings.bot_owner_telegram_id,
        max_text_chars=settings.ai_max_text_chars,
        max_image_bytes=settings.ai_max_image_bytes,
        max_image_pixels=settings.ai_max_image_pixels,
        daily_user_limit=settings.ai_daily_user_limit,
        monthly_global_limit=settings.ai_monthly_global_limit,
    )
    readiness = ReadinessService(session_factory)
    ai_readiness = AiReadinessInputService(
        session_factory,
        ai_router,
        assisted,
        readiness,
        max_text_chars=settings.ai_max_text_chars,
        max_audio_bytes=settings.ai_max_audio_bytes,
    )
    return AppServices(
        users=users,
        activities=ActivityService(session_factory, users, recommendation_lifecycle),
        groups=GroupService(session_factory),
        imports=ImportService(
            session_factory,
            users,
            storage,
            max_upload_bytes=settings.max_upload_bytes,
            max_archive_uncompressed_bytes=settings.max_archive_uncompressed_bytes,
            max_archive_entries=settings.max_archive_entries,
            max_archive_ratio=settings.max_archive_ratio,
            recommendation_lifecycle=recommendation_lifecycle,
        ),
        health_connect=health_connect,
        outbox=TelegramOutboxService(session_factory),
        coach=coach,
        monthly=MonthlyReportService(session_factory),
        assisted=assisted,
        goals=GoalService(session_factory),
        readiness=readiness,
        next_run=NextRunService(session_factory, health_connect),
        ai_readiness=ai_readiness,
    )
