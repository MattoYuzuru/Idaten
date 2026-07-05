from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_health_and_readiness() -> None:
    app = create_app(Settings(database_url="sqlite+aiosqlite:///:memory:", _env_file=None))
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/ready").json() == {"status": "ready", "database": "ok"}
