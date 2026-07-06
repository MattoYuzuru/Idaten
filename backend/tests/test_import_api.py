import asyncio
import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.db.base import Base
from app.main import create_app
from app.users.models import TelegramAccount, User

CSV = (
    b"started_at,distance_m,elapsed_time_sec,activity_type,title,external_id\n"
    b"2026-07-06T06:00:00+00:00,5000,1800,RUN,Tempo,http-1\n"
)


async def _prepare_database(url: str) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with engine.begin() as connection:
        user_id = uuid.uuid4()
        await connection.execute(
            User.__table__.insert().values(
                id=user_id,
                display_name="API Runner",
                timezone="Europe/Moscow",
                locale="ru",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await connection.execute(
            TelegramAccount.__table__.insert().values(
                id=uuid.uuid4(),
                user_id=user_id,
                telegram_user_id=42,
                username="runner",
                first_name="Runner",
                last_name=None,
                private_chat_id=42,
                created_at=datetime.now(UTC),
            )
        )
    await engine.dispose()


def test_import_api_requires_configured_valid_token(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'disabled.sqlite'}"
    app = create_app(
        Settings(
            database_url=database_url,
            storage_path=str(tmp_path / "storage"),
            _env_file=None,
        )
    )
    with TestClient(app) as client:
        assert client.get("/imports", headers={"X-Telegram-User-Id": "42"}).status_code == 503


def test_http_upload_preview_and_confirm(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'api.sqlite'}"
    asyncio.run(_prepare_database(database_url))
    app = create_app(
        Settings(
            database_url=database_url,
            storage_path=str(tmp_path / "storage"),
            import_api_token=SecretStr("test-token"),
            _env_file=None,
        )
    )
    headers = {
        "X-Telegram-User-Id": "42",
        "X-Idaten-Import-Token": "test-token",
    }
    with TestClient(app) as client:
        assert (
            client.get(
                "/imports",
                headers={**headers, "X-Idaten-Import-Token": "wrong"},
            ).status_code
            == 403
        )
        upload = client.post(
            "/imports",
            headers=headers,
            files={"file": ("activity.csv", CSV, "text/csv")},
        )
        assert upload.status_code == 200, upload.text
        preview = upload.json()
        assert preview["source_type"] == "CSV"
        confirm = client.post(
            f"/imports/{preview['import_id']}/confirm",
            headers=headers,
            json={"overrides": {"title": "Validated override"}},
        )
        assert confirm.status_code == 200, confirm.text
        assert confirm.json()["created"] is True
        history = client.get("/imports", headers=headers)
        assert history.status_code == 200
        assert history.json()[0]["status"] == "CONFIRMED"
