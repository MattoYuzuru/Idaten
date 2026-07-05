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

    @property
    def bot_token(self) -> str | None:
        if self.telegram_bot_token is None:
            return None
        value = self.telegram_bot_token.get_secret_value().strip()
        return value or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
