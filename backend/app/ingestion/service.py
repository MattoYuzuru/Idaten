import gzip
import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.activities.models import (
    Activity,
    ActivityVisibility,
    CoachReport,
    ReportType,
)
from app.activities.repository import ActivityRepository
from app.activities.schemas import ActivitySummary
from app.analytics.metrics import (
    calculate_pace_sec_per_km,
    calculate_speed_mps,
    format_local_week_period,
    local_week_bounds,
)
from app.coach.lifecycle import RecommendationLifecycle
from app.coach.report_builder import build_after_run_report
from app.ingestion.adapters.registry import AdapterRegistry
from app.ingestion.adapters.track import build_splits
from app.ingestion.models import (
    ActivityImport,
    ActivitySeries,
    ActivitySplit,
    ImportStatus,
    RawArtifact,
)
from app.ingestion.repository import ImportRepository
from app.ingestion.schemas import (
    ConfirmedImport,
    ImportError,
    ImportHistoryItem,
    ImportOverrides,
    ImportPreview,
    NormalizedActivity,
    apply_overrides,
    validate_normalized,
)
from app.ingestion.security import validate_upload
from app.storage.service import StorageService
from app.users.models import User
from app.users.repository import UserRepository
from app.users.schemas import TelegramIdentity
from app.users.service import UserService


class ImportService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        user_service: UserService,
        storage: StorageService,
        recommendation_lifecycle: RecommendationLifecycle | None = None,
        *,
        max_upload_bytes: int,
        max_archive_uncompressed_bytes: int,
        max_archive_entries: int,
        max_archive_ratio: int,
    ) -> None:
        self.session_factory = session_factory
        self.user_service = user_service
        self.storage = storage
        self.recommendation_lifecycle = recommendation_lifecycle or RecommendationLifecycle()
        self.registry = AdapterRegistry()
        self.max_upload_bytes = max_upload_bytes
        self.max_archive_uncompressed_bytes = max_archive_uncompressed_bytes
        self.max_archive_entries = max_archive_entries
        self.max_archive_ratio = max_archive_ratio

    def validate_declared_size(self, size_bytes: int | None) -> None:
        if size_bytes is not None and size_bytes > self.max_upload_bytes:
            raise ImportError("Файл превышает допустимый размер.", code="UPLOAD_TOO_LARGE")

    async def upload_for_telegram(
        self,
        identity: TelegramIdentity,
        *,
        filename: str,
        media_type: str | None,
        content: bytes,
    ) -> ImportPreview:
        user = await self.user_service.register(identity)
        return await self._upload(user, filename=filename, media_type=media_type, content=content)

    async def upload_for_user(
        self,
        telegram_user_id: int,
        *,
        filename: str,
        media_type: str | None,
        content: bytes,
    ) -> ImportPreview:
        async with self.session_factory() as session:
            user = await self._require_user(session, telegram_user_id)
        return await self._upload(user, filename=filename, media_type=media_type, content=content)

    async def _upload(
        self, user: User, *, filename: str, media_type: str | None, content: bytes
    ) -> ImportPreview:
        safe = validate_upload(
            filename,
            media_type,
            content,
            max_upload_bytes=self.max_upload_bytes,
            max_archive_uncompressed_bytes=self.max_archive_uncompressed_bytes,
            max_archive_entries=self.max_archive_entries,
            max_archive_ratio=self.max_archive_ratio,
        )
        digest = hashlib.sha256(content).hexdigest()
        existing = await self._existing_import(user.id, digest)
        if existing is not None:
            if existing.status == ImportStatus.CANCELLED and existing.normalized_json is not None:
                async with self.session_factory.begin() as session:
                    cancelled = await ImportRepository(session).get_import(
                        existing.id, user.id, for_update=True
                    )
                    if cancelled is not None and cancelled.status == ImportStatus.CANCELLED:
                        cancelled.status = ImportStatus.PREVIEW
                return await self.preview(user.id, existing.id)
            return await self._preview(existing, user.id)

        stored = await self.storage.save("raw", content, safe.raw_suffix)
        import_id = uuid.uuid4()
        artifact_id = uuid.uuid4()
        try:
            async with self.session_factory.begin() as session:
                repository = ImportRepository(session)
                repository.add(
                    RawArtifact(
                        id=artifact_id,
                        user_id=user.id,
                        storage_uri=stored.uri,
                        sha256=digest,
                        original_filename=safe.display_filename,
                        media_type=(media_type or "application/octet-stream")[:127],
                        size_bytes=len(content),
                        created_at=datetime.now(UTC),
                    )
                )
                repository.add(
                    ActivityImport(
                        id=import_id,
                        user_id=user.id,
                        raw_artifact_id=artifact_id,
                        status=ImportStatus.RECEIVED,
                    )
                )
        except IntegrityError as error:
            await self.storage.delete(stored.uri)
            concurrent = await self._existing_import(user.id, digest)
            if concurrent is None:
                raise ImportError(
                    "Не удалось зарегистрировать импорт.", code="IMPORT_CONFLICT"
                ) from error
            return await self._preview(concurrent, user.id)

        try:
            normalized = self.registry.parse(safe.parse_suffix, safe.parse_content, user.timezone)
            validate_normalized(normalized)
            series_uri, series_summary = await self._save_series(normalized)
        except ImportError as error:
            await self._mark_failed(import_id, user.id, error)
            raise

        async with self.session_factory.begin() as session:
            record = await ImportRepository(session).get_import(import_id, user.id, for_update=True)
            if record is None:
                raise ImportError("Импорт не найден.", code="IMPORT_NOT_FOUND")
            record.status = ImportStatus.PREVIEW
            record.source_type = normalized.source_type
            record.normalized_json = normalized.to_draft_json()
            record.draft_series_uri = series_uri
            record.series_summary_json = series_summary
        return await self.preview(user.id, import_id)

    async def preview(self, user_id: uuid.UUID, import_id: uuid.UUID) -> ImportPreview:
        async with self.session_factory() as session:
            record = await ImportRepository(session).get_import(import_id, user_id)
            if record is None:
                raise ImportError("Импорт не найден.", code="IMPORT_NOT_FOUND")
            return await self._preview_from_record(session, record)

    async def preview_for_user(self, telegram_user_id: int, import_id: uuid.UUID) -> ImportPreview:
        async with self.session_factory() as session:
            user = await self._require_user(session, telegram_user_id)
        return await self.preview(user.id, import_id)

    async def confirm(
        self,
        telegram_user_id: int,
        import_id: uuid.UUID,
        *,
        overrides: ImportOverrides | None = None,
        accept_possible_duplicate: bool = False,
    ) -> ConfirmedImport:
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            locked_user = await UserRepository(session).get_by_id_for_update(user.id)
            if locked_user is None:
                raise ImportError("Пользователь не найден.", code="USER_NOT_FOUND")
            user = locked_user
            repository = ImportRepository(session)
            record = await repository.get_import(import_id, user.id, for_update=True)
            if record is None:
                raise ImportError("Импорт не найден.", code="IMPORT_NOT_FOUND")
            if record.status in {ImportStatus.CONFIRMED, ImportStatus.DUPLICATE}:
                if record.confirmed_activity_id is None:
                    raise ImportError("Импорт поврежден.", code="INVALID_IMPORT_STATE")
                return ConfirmedImport(record.id, record.confirmed_activity_id, False, None)
            if record.status != ImportStatus.PREVIEW or record.normalized_json is None:
                raise ImportError("Импорт не готов к подтверждению.", code="INVALID_IMPORT_STATE")

            normalized = apply_overrides(
                NormalizedActivity.from_draft_json(record.normalized_json), overrides
            )
            validate_normalized(normalized)
            exact = await repository.exact_activity(
                user.id, normalized.source_type, normalized.external_id
            )
            if exact is not None:
                record.status = ImportStatus.DUPLICATE
                record.confirmed_activity_id = exact.id
                return ConfirmedImport(record.id, exact.id, False, None)
            candidates = await repository.duplicate_candidates(
                user.id,
                started_at=normalized.started_at,
                distance_m=normalized.distance_m,
                elapsed_time_sec=normalized.elapsed_time_sec,
            )
            if candidates and not accept_possible_duplicate:
                raise ImportError(
                    "Найдена похожая активность; требуется явное подтверждение.",
                    code="POSSIBLE_DUPLICATE",
                )

            activity_repository = ActivityRepository(session)
            source = await activity_repository.get_or_create_source(user.id, normalized.source_type)
            pace = calculate_pace_sec_per_km(normalized.distance_m, normalized.elapsed_time_sec)
            activity = Activity(
                user_id=user.id,
                source_id=source.id,
                source_type=normalized.source_type,
                external_id=normalized.external_id,
                activity_type=normalized.activity_type,
                title=normalized.title,
                started_at=normalized.started_at,
                timezone=normalized.timezone,
                distance_m=normalized.distance_m,
                elapsed_time_sec=normalized.elapsed_time_sec,
                moving_time_sec=normalized.moving_time_sec,
                avg_pace_sec_per_km=pace,
                avg_speed_mps=calculate_speed_mps(
                    normalized.distance_m, normalized.elapsed_time_sec
                ),
                avg_hr=normalized.avg_hr,
                max_hr=normalized.max_hr,
                visibility=ActivityVisibility.PRIVATE,
            )
            activity_repository.add(activity)
            await session.flush()
            await self.recommendation_lifecycle.activity_recorded(session, user.id, activity)
            splits = normalized.splits or build_splits(
                normalized.distance_m, normalized.elapsed_time_sec
            )
            for split in splits:
                repository.add(
                    ActivitySplit(
                        activity_id=activity.id,
                        split_index=split.index,
                        distance_m=split.distance_m,
                        elapsed_time_sec=split.elapsed_time_sec,
                        moving_time_sec=split.moving_time_sec,
                        avg_pace_sec_per_km=calculate_pace_sec_per_km(
                            split.distance_m, split.elapsed_time_sec
                        ),
                    )
                )
            if record.draft_series_uri and record.series_summary_json:
                repository.add(
                    ActivitySeries(
                        activity_id=activity.id,
                        series_kind="TRACK",
                        storage_uri=record.draft_series_uri,
                        content_encoding="gzip",
                        content_type="application/json",
                        point_count=int(record.series_summary_json["point_count"]),
                        summary_json=record.series_summary_json,
                        created_at=datetime.now(UTC),
                    )
                )
            summary = ActivitySummary(
                activity_id=activity.id,
                distance_m=activity.distance_m,
                elapsed_time_sec=activity.elapsed_time_sec,
                avg_pace_sec_per_km=activity.avg_pace_sec_per_km,
            )
            week_start, week_end = local_week_bounds(activity.started_at, user.timezone)
            week_stats = await activity_repository.aggregate(
                user.id, started_from=week_start, started_before=week_end
            )
            report = build_after_run_report(
                summary,
                week_stats,
                format_local_week_period(week_start, week_end, user.timezone),
            )
            repository.add(
                CoachReport(
                    user_id=user.id,
                    activity_id=activity.id,
                    report_type=ReportType.AFTER_RUN,
                    facts_json=report.facts_json,
                    rule_result_json=report.rule_result_json,
                    message_private=report.message,
                )
            )
            record.normalized_json = normalized.to_draft_json()
            record.status = ImportStatus.CONFIRMED
            record.confirmed_activity_id = activity.id
            return ConfirmedImport(record.id, activity.id, True, report.message)

    async def cancel(self, telegram_user_id: int, import_id: uuid.UUID) -> None:
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            record = await ImportRepository(session).get_import(import_id, user.id, for_update=True)
            if record is None:
                raise ImportError("Импорт не найден.", code="IMPORT_NOT_FOUND")
            if record.status == ImportStatus.PREVIEW:
                record.status = ImportStatus.CANCELLED

    async def history(self, telegram_user_id: int) -> tuple[ImportHistoryItem, ...]:
        async with self.session_factory() as session:
            user = await self._require_user(session, telegram_user_id)
            rows = await ImportRepository(session).history(user.id)
            return tuple(
                ImportHistoryItem(
                    import_id=record.id,
                    filename=artifact.original_filename,
                    status=record.status.value,
                    source_type=record.source_type,
                    created_at=record.created_at,
                    activity_id=record.confirmed_activity_id,
                    error_code=record.error_code,
                )
                for record, artifact in rows
            )

    async def _existing_import(self, user_id: uuid.UUID, digest: str) -> ActivityImport | None:
        async with self.session_factory() as session:
            repository = ImportRepository(session)
            artifact = await repository.artifact_by_hash(user_id, digest)
            return await repository.import_by_artifact(artifact.id) if artifact else None

    async def _preview(self, record: ActivityImport, user_id: uuid.UUID) -> ImportPreview:
        if record.status == ImportStatus.FAILED:
            raise ImportError(
                record.error_message or "Предыдущий импорт этого файла завершился ошибкой.",
                code=record.error_code or "IMPORT_ERROR",
            )
        if record.status in {ImportStatus.CONFIRMED, ImportStatus.DUPLICATE}:
            if record.confirmed_activity_id is None or record.normalized_json is None:
                raise ImportError("Импорт поврежден.", code="INVALID_IMPORT_STATE")
        if record.normalized_json is None:
            raise ImportError("Импорт еще обрабатывается.", code="IMPORT_IN_PROGRESS")
        async with self.session_factory() as session:
            attached = await ImportRepository(session).get_import(record.id, user_id)
            if attached is None:
                raise ImportError("Импорт не найден.", code="IMPORT_NOT_FOUND")
            return await self._preview_from_record(session, attached)

    async def _preview_from_record(
        self, session: AsyncSession, record: ActivityImport
    ) -> ImportPreview:
        if record.normalized_json is None or record.source_type is None:
            raise ImportError("Импорт не готов к preview.", code="INVALID_IMPORT_STATE")
        normalized = NormalizedActivity.from_draft_json(record.normalized_json)
        repository = ImportRepository(session)
        exact = await repository.exact_activity(
            record.user_id, normalized.source_type, normalized.external_id
        )
        candidates = await repository.duplicate_candidates(
            record.user_id,
            started_at=normalized.started_at,
            distance_m=normalized.distance_m,
            elapsed_time_sec=normalized.elapsed_time_sec,
        )
        return ImportPreview(
            import_id=record.id,
            source_type=record.source_type,
            started_at=normalized.started_at,
            distance_m=normalized.distance_m,
            elapsed_time_sec=normalized.elapsed_time_sec,
            title=normalized.title,
            duplicate_candidates=candidates,
            exact_duplicate_activity_id=exact.id if exact else None,
        )

    async def _save_series(
        self, normalized: NormalizedActivity
    ) -> tuple[str | None, dict[str, Any] | None]:
        if not normalized.track_points:
            return None, None
        payload = [
            {
                "timestamp": point.timestamp.isoformat(),
                "latitude": point.latitude,
                "longitude": point.longitude,
                "elevation_m": point.elevation_m,
                "heart_rate": point.heart_rate,
                "speed_mps": point.speed_mps,
                "cadence_spm": point.cadence_spm,
            }
            for point in normalized.track_points
        ]
        compressed = gzip.compress(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        )
        stored = await self.storage.save("series", compressed, ".json.gz")
        summary: dict[str, Any] = {
            "point_count": len(normalized.track_points),
            "has_gps": any(point.latitude is not None for point in normalized.track_points),
            "has_hr": any(point.heart_rate is not None for point in normalized.track_points),
        }
        return stored.uri, summary

    async def _mark_failed(
        self, import_id: uuid.UUID, user_id: uuid.UUID, error: ImportError
    ) -> None:
        async with self.session_factory.begin() as session:
            record = await ImportRepository(session).get_import(import_id, user_id, for_update=True)
            if record is not None:
                record.status = ImportStatus.FAILED
                record.error_code = error.code[:64]
                record.error_message = str(error)[:255]

    @staticmethod
    async def _require_user(session: AsyncSession, telegram_user_id: int) -> User:
        found = await UserRepository(session).get_by_telegram_id(telegram_user_id)
        if found is None:
            raise ImportError("Сначала выполните /start.", code="USER_NOT_FOUND")
        return found[0]
