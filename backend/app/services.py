from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.activities.service import ActivityService
from app.assisted.provider import (
    ActivityExtractionProvider,
    ExtractionProviderName,
    NoneActivityExtractionProvider,
    OpenAIActivityExtractionProvider,
)
from app.assisted.service import AssistedActivityService
from app.coach.provider import (
    JsonHttpWordingProvider,
    LLMProviderName,
    NoneWordingProvider,
    ProviderExecutor,
    WordingProvider,
)
from app.coach.service import CoachService
from app.core.config import Settings
from app.groups.monthly_service import MonthlyReportService
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
    coach: CoachService
    monthly: MonthlyReportService
    assisted: AssistedActivityService


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
    provider_name = LLMProviderName(settings.llm_provider.upper())
    endpoints = {
        LLMProviderName.OPENAI: "https://api.openai.com/v1/chat/completions",
        LLMProviderName.GEMINI: "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        LLMProviderName.DEEPSEEK: "https://api.deepseek.com/chat/completions",
        LLMProviderName.OPENROUTER: "https://openrouter.ai/api/v1/chat/completions",
        LLMProviderName.OLLAMA: "http://localhost:11434/api/chat",
    }
    provider: WordingProvider
    if provider_name == LLMProviderName.NONE or not settings.llm_model.strip():
        provider = NoneWordingProvider()
    else:
        provider = JsonHttpWordingProvider(
            provider_name,
            settings.llm_model,
            settings.llm_endpoint or endpoints[provider_name],
            settings.wording_api_key,
            request_timeout_seconds=settings.llm_timeout_seconds,
        )
    coach = CoachService(
        session_factory,
        ProviderExecutor(
            provider,
            timeout_seconds=settings.llm_timeout_seconds,
            retries=settings.llm_retries,
        ),
    )
    extraction_provider: ActivityExtractionProvider = NoneActivityExtractionProvider()
    extraction_provider_name = ExtractionProviderName(settings.activity_extraction_provider.upper())
    if (
        extraction_provider_name == ExtractionProviderName.OPENAI
        and settings.extraction_api_key
        and settings.activity_extraction_model.strip()
    ):
        extraction_provider = OpenAIActivityExtractionProvider(
            settings.activity_extraction_model,
            settings.extraction_api_key,
            settings.activity_extraction_endpoint,
            request_timeout_seconds=settings.activity_extraction_timeout_seconds,
        )
    assisted = AssistedActivityService(
        session_factory,
        users,
        extraction_provider,
        enabled=(
            settings.activity_extraction_enabled and settings.bot_owner_telegram_id is not None
        ),
        owner_telegram_user_id=settings.bot_owner_telegram_id,
        max_text_chars=settings.activity_extraction_max_text_chars,
        max_image_bytes=settings.activity_extraction_max_image_bytes,
        max_image_pixels=settings.activity_extraction_max_image_pixels,
        daily_user_limit=settings.activity_extraction_daily_user_limit,
        monthly_global_limit=settings.activity_extraction_monthly_global_limit,
        timeout_seconds=settings.activity_extraction_timeout_seconds,
        retries=settings.activity_extraction_retries,
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
        coach=coach,
        monthly=MonthlyReportService(session_factory),
        assisted=assisted,
    )
