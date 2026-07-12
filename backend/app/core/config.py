from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Idaten"
    database_url: str = "postgresql+asyncpg://idaten:change-me@localhost:5432/idaten"
    telegram_bot_token: SecretStr | None = None
    default_timezone: str = "Europe/Moscow"
    default_locale: str = "ru"
    log_level: str = "INFO"
    storage_path: str = "/data/idaten"
    max_upload_bytes: int = 10 * 1024 * 1024
    max_archive_uncompressed_bytes: int = 50 * 1024 * 1024
    max_archive_entries: int = 10
    max_archive_ratio: int = 100
    import_api_token: SecretStr | None = None
    health_connect_security_pepper: SecretStr | None = None
    health_connect_link_ttl_seconds: int = 600
    health_connect_link_attempt_limit: int = 5
    health_connect_link_attempt_window_seconds: int = 900
    health_connect_max_batch_size: int = 25
    outbox_poll_seconds: int = 5
    bot_owner_telegram_id: int | None = None
    ai_enabled: bool = False
    ai_default_provider: str = "OPENAI"
    ai_openai_api_key: SecretStr | None = None
    ai_openai_endpoint: str = "https://api.openai.com/v1"
    ai_task_activity_extraction_provider: str = "OPENAI"
    ai_task_activity_extraction_model: str = "gpt-4.1-nano"
    ai_task_readiness_extraction_provider: str = "OPENAI"
    ai_task_readiness_extraction_model: str = "gpt-4.1-nano"
    ai_task_voice_transcription_provider: str = "OPENAI"
    ai_task_voice_transcription_model: str = "gpt-4o-mini-transcribe"
    ai_timeout_seconds: float = 15.0
    ai_retries: int = 1
    ai_max_text_chars: int = 4_000
    ai_max_image_bytes: int = 5 * 1024 * 1024
    ai_max_image_pixels: int = 20_000_000
    ai_max_audio_bytes: int = 10 * 1024 * 1024
    ai_daily_user_limit: int = 5
    ai_monthly_global_limit: int = 100

    @property
    def bot_token(self) -> str | None:
        if self.telegram_bot_token is None:
            return None
        value = self.telegram_bot_token.get_secret_value().strip()
        return value or None

    @property
    def api_token(self) -> str | None:
        if self.import_api_token is None:
            return None
        value = self.import_api_token.get_secret_value().strip()
        return value or None

    @property
    def device_security_pepper(self) -> str | None:
        if self.health_connect_security_pepper is None:
            return None
        value = self.health_connect_security_pepper.get_secret_value().strip()
        return value or None

    @property
    def ai_api_key(self) -> str | None:
        if self.ai_openai_api_key is None:
            return None
        value = self.ai_openai_api_key.get_secret_value().strip()
        return value or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
