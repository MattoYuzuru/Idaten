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


@lru_cache
def get_settings() -> Settings:
    return Settings()
