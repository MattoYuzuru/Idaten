from alembic.config import Config

from app.db.alembic import escape_config_percent


def test_percent_encoded_password_is_safe_for_alembic_config() -> None:
    database_url = "postgresql+asyncpg://idaten:p%40ss%21@postgres:5432/idaten"

    escaped = escape_config_percent(database_url)
    assert escaped == ("postgresql+asyncpg://idaten:p%%40ss%%21@postgres:5432/idaten")
    config = Config()
    config.set_main_option("sqlalchemy.url", escaped)

    assert config.get_main_option("sqlalchemy.url") == database_url
