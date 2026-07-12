import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.db.base import Base
from app.main import create_app
from app.users.models import TelegramAccount, User


async def prepare_database(url: str) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        user_id = uuid.uuid4()
        await connection.execute(
            User.__table__.insert().values(
                id=user_id,
                display_name="Runner",
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


def test_link_sync_status_and_safe_item_error(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'health-connect.sqlite'}"
    asyncio.run(prepare_database(database_url))
    app = create_app(
        Settings(
            database_url=database_url,
            storage_path=str(tmp_path / "storage"),
            import_api_token=SecretStr("operator-token"),
            health_connect_security_pepper=SecretStr("test-pepper"),
            _env_file=None,
        )
    )
    with TestClient(app) as client:
        denied_start = client.post("/health-connect/link/start", json={"telegram_user_id": 42})
        assert denied_start.status_code == 403
        started = client.post(
            "/health-connect/link/start",
            headers={"X-Idaten-Import-Token": "operator-token"},
            json={"telegram_user_id": 42},
        )
        assert started.status_code == 200
        completed = client.post(
            "/health-connect/link/complete",
            json={
                "code": started.json()["code"],
                "installation_id": "installation-1",
                "device_name": "Pixel",
                "device_model": "Pixel 9",
            },
        )
        assert completed.status_code == 200
        token = completed.json()["token"]
        assert client.get("/health-connect/sync/status").status_code == 401

        sleep_payload = {
            "external_id": "sleep-api-1",
            "started_at": "2026-07-11T21:00:00Z",
            "ended_at": "2026-07-12T05:00:00Z",
            "duration_sec": 28_800,
            "data_origin": "com.samsung.health",
            "observed_at": "2026-07-12T06:00:00Z",
        }
        assert client.post("/health-connect/sync/sleep", json=sleep_payload).status_code == 401
        sleep = client.post(
            "/health-connect/sync/sleep",
            headers={"Authorization": f"Bearer {token}"},
            json=sleep_payload,
        )
        assert sleep.status_code == 200
        assert sleep.json()["created"] is True
        repeated_sleep = client.post(
            "/health-connect/sync/sleep",
            headers={"Authorization": f"Bearer {token}"},
            json=sleep_payload,
        )
        assert repeated_sleep.status_code == 200
        assert repeated_sleep.json() == {
            "summary_id": sleep.json()["summary_id"],
            "created": False,
        }
        raw_stages = client.post(
            "/health-connect/sync/sleep",
            headers={"Authorization": f"Bearer {token}"},
            json={**sleep_payload, "stages": []},
        )
        assert raw_stages.status_code == 422

        sync = client.post(
            "/health-connect/sync/activities",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "cursor": "cursor-1",
                "batch_id": "api-delivery-1",
                "found_count": 3,
                "skipped_count": 1,
                "activities": [
                    {
                        "external_id": "api-valid",
                        "started_at": "2026-07-06T06:00:00Z",
                        "timezone": "Europe/Moscow",
                        "distance_m": 5000,
                        "elapsed_time_sec": 1800,
                    },
                    {
                        "external_id": "api-invalid",
                        "started_at": "2026-07-06T06:00:00Z",
                        "timezone": "Europe/Moscow",
                        "distance_m": -1,
                        "elapsed_time_sec": 1800,
                    },
                ],
            },
        )
        assert sync.status_code == 200
        assert [item["external_id"] for item in sync.json()["items"]] == [
            "api-invalid",
            "api-valid",
        ]
        assert [item["status"] for item in sync.json()["items"]] == ["error", "saved"]
        assert sync.json()["items"][0]["error_code"] == "INVALID_DISTANCE"
        assert sync.json()["counts"] == {
            "saved": 1,
            "duplicate": 0,
            "skipped": 1,
            "error": 1,
        }
        assert "traceback" not in sync.text.lower()
        status_response = client.get(
            "/health-connect/sync/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert status_response.status_code == 200
        assert status_response.json()["last_sync_status"] == "PARTIAL"
