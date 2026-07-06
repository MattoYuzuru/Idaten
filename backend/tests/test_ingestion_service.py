import gzip
import json
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.activities.models import Activity, ActivityVisibility, CoachReport
from app.core.config import Settings
from app.db.base import Base
from app.groups.schemas import GroupError
from app.ingestion.models import (
    ActivityImport,
    ActivitySeries,
    ActivitySplit,
    ImportStatus,
    RawArtifact,
)
from app.ingestion.schemas import ImportError, ImportOverrides
from app.services import AppServices, build_services
from app.users.schemas import TelegramIdentity

GPX = b"""<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
<trk><name>Morning run</name><trkseg>
<trkpt lat="55.7500" lon="37.6100"><time>2026-07-06T06:00:00Z</time></trkpt>
<trkpt lat="55.7590" lon="37.6100"><time>2026-07-06T06:06:00Z</time></trkpt>
</trkseg></trk></gpx>"""

GROUP_ID = -1_001_234_567_890


@pytest.fixture
async def import_context(
    tmp_path,
) -> AsyncIterator[tuple[AppServices, async_sessionmaker[AsyncSession]]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    services = build_services(
        session_factory,
        Settings(
            database_url="sqlite+aiosqlite://",
            storage_path=str(tmp_path / "storage"),
            default_timezone="Europe/Moscow",
            _env_file=None,
        ),
    )
    yield services, session_factory
    await engine.dispose()


def identity() -> TelegramIdentity:
    return TelegramIdentity(
        telegram_user_id=42,
        private_chat_id=42,
        username="runner",
        first_name="Матвей",
    )


def csv_activity(
    *,
    started_at: str = "2026-07-06T06:00:00+00:00",
    distance_m: int = 5_000,
    elapsed: int = 1_800,
    external_id: str = "csv-1",
    title: str = "Tempo",
) -> bytes:
    return (
        "started_at,distance_m,elapsed_time_sec,activity_type,title,external_id\n"
        f"{started_at},{distance_m},{elapsed},RUN,{title},{external_id}\n"
    ).encode()


@pytest.mark.asyncio
async def test_preview_confirm_and_repeat_are_private_and_idempotent(
    import_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = import_context
    preview = await services.imports.upload_for_telegram(
        identity(),
        filename="../../personal-name.gpx",
        media_type="application/gpx+xml",
        content=GPX,
    )

    async with session_factory() as session:
        assert await session.scalar(select(func.count(Activity.id))) == 0
        artifact = (await session.execute(select(RawArtifact))).scalar_one()
        record = (await session.execute(select(ActivityImport))).scalar_one()
    assert record.status == ImportStatus.PREVIEW
    assert "personal-name" not in artifact.storage_uri

    await services.groups.setup_group(42, GROUP_ID, "Idaten", actor_is_admin=True)
    confirmed = await services.imports.confirm(42, preview.import_id)
    repeated = await services.imports.confirm(42, preview.import_id)
    same_upload = await services.imports.upload_for_user(
        42, filename="renamed.gpx", media_type="application/gpx+xml", content=GPX
    )

    assert confirmed.created
    assert not repeated.created
    assert repeated.activity_id == confirmed.activity_id
    assert same_upload.import_id == preview.import_id
    assert await services.groups.leaderboard(GROUP_ID) == ()
    with pytest.raises(GroupError, match="Privacy"):
        await services.groups.grant_and_prepare_publication(42, GROUP_ID, confirmed.activity_id)

    async with session_factory() as session:
        activity = await session.get(Activity, confirmed.activity_id)
        assert activity is not None
        assert activity.visibility == ActivityVisibility.PRIVATE
        assert await session.scalar(select(func.count(Activity.id))) == 1
        assert await session.scalar(select(func.count(ActivitySplit.id))) >= 1
        assert await session.scalar(select(func.count(CoachReport.id))) == 1
        series = (await session.execute(select(ActivitySeries))).scalar_one()
    compressed = await services.imports.storage.read(series.storage_uri)
    points = json.loads(gzip.decompress(compressed))
    assert len(points) == series.point_count == 2


@pytest.mark.asyncio
async def test_fuzzy_duplicate_requires_explicit_accept_and_overrides_are_revalidated(
    import_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = import_context
    first = await services.imports.upload_for_telegram(
        identity(), filename="first.csv", media_type="text/csv", content=csv_activity()
    )
    await services.imports.confirm(42, first.import_id)
    second = await services.imports.upload_for_user(
        42,
        filename="second.csv",
        media_type="text/csv",
        content=csv_activity(
            started_at="2026-07-06T06:00:30+00:00",
            distance_m=5_050,
            elapsed=1_820,
            external_id="csv-2",
        ),
    )
    assert len(second.duplicate_candidates) == 1

    with pytest.raises(ImportError) as duplicate_error:
        await services.imports.confirm(42, second.import_id)
    assert duplicate_error.value.code == "POSSIBLE_DUPLICATE"
    with pytest.raises(ImportError) as override_error:
        await services.imports.confirm(
            42,
            second.import_id,
            overrides=ImportOverrides(distance_m=-1),
            accept_possible_duplicate=True,
        )
    assert override_error.value.code == "INVALID_DISTANCE"

    confirmed = await services.imports.confirm(42, second.import_id, accept_possible_duplicate=True)
    assert confirmed.created
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Activity.id))) == 2


@pytest.mark.asyncio
async def test_external_id_duplicate_maps_to_existing_activity(
    import_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = import_context
    first = await services.imports.upload_for_telegram(
        identity(), filename="first.csv", media_type="text/csv", content=csv_activity()
    )
    first_result = await services.imports.confirm(42, first.import_id)
    second = await services.imports.upload_for_user(
        42,
        filename="second.csv",
        media_type="text/csv",
        content=csv_activity(title="Different hash"),
    )

    assert second.exact_duplicate_activity_id == first_result.activity_id
    duplicate = await services.imports.confirm(42, second.import_id)

    assert not duplicate.created
    assert duplicate.activity_id == first_result.activity_id
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Activity.id))) == 1


@pytest.mark.asyncio
async def test_parser_failure_is_diagnosable_without_payload_leak(
    import_context: tuple[AppServices, async_sessionmaker[AsyncSession]],
) -> None:
    services, session_factory = import_context
    secret_payload = b"SECRET_PRIVATE_PAYLOAD"

    with pytest.raises(ImportError) as captured:
        await services.imports.upload_for_telegram(
            identity(),
            filename="broken.gpx",
            media_type="application/gpx+xml",
            content=secret_payload,
        )
    assert captured.value.code == "GPX_PARSE_ERROR"

    async with session_factory() as session:
        record = (await session.execute(select(ActivityImport))).scalar_one()
    assert record.status == ImportStatus.FAILED
    assert record.error_code == "GPX_PARSE_ERROR"
    assert "SECRET" not in (record.error_message or "")
    history = await services.imports.history(42)
    assert history[0].error_code == "GPX_PARSE_ERROR"
