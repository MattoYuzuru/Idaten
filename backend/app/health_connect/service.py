import gzip
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.activities.models import Activity, ActivityVisibility, CoachReport, ReportType, SourceType
from app.activities.repository import ActivityRepository
from app.activities.schemas import ActivitySummary
from app.analytics.metrics import calculate_pace_sec_per_km, calculate_speed_mps, local_week_bounds
from app.coach.report_builder import build_after_run_report
from app.ingestion.adapters.track import build_splits
from app.ingestion.models import ActivitySeries, ActivitySplit
from app.ingestion.schemas import ImportError, NormalizedActivity, validate_normalized
from app.storage.service import StorageService
from app.users.models import User
from app.users.repository import UserRepository
from app.users.schemas import TelegramIdentity
from app.users.service import UserService

from .adapter import HealthConnectAdapter
from .models import (
    Device,
    DeviceLinkAttempt,
    DeviceLinkCode,
    DeviceScope,
    HealthConnectSyncBatch,
    SyncStatus,
    TelegramOutbox,
)
from .repository import HealthConnectRepository
from .schemas import (
    DeviceStatus,
    DeviceSummary,
    HealthConnectError,
    HealthConnectRun,
    LinkCode,
    LinkedDevice,
    SyncBatchResult,
    SyncItemResult,
    SyncItemState,
)
from .security import hashes_match, keyed_hash, new_device_token, new_link_code, token_device_id
from .summary import build_batch_summary

logger = logging.getLogger(__name__)


class HealthConnectService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        user_service: UserService,
        storage: StorageService,
        *,
        security_pepper: str | None,
        link_ttl_seconds: int,
        link_attempt_limit: int,
        link_attempt_window_seconds: int,
        max_batch_size: int,
    ) -> None:
        self.session_factory = session_factory
        self.user_service = user_service
        self.storage = storage
        self.security_pepper = security_pepper
        self.link_ttl_seconds = link_ttl_seconds
        self.link_attempt_limit = link_attempt_limit
        self.link_attempt_window_seconds = link_attempt_window_seconds
        self.max_batch_size = max_batch_size
        self.adapter = HealthConnectAdapter()

    async def start_link_for_identity(self, identity: TelegramIdentity) -> LinkCode:
        user = await self.user_service.register(identity)
        return await self._start_link(user.id)

    async def start_link_for_user(self, telegram_user_id: int) -> LinkCode:
        async with self.session_factory() as session:
            found = await UserRepository(session).get_by_telegram_id(telegram_user_id)
            if found is None:
                raise HealthConnectError("Сначала выполните /start.", code="USER_NOT_FOUND")
            user_id = found[0].id
        return await self._start_link(user_id)

    async def _start_link(self, user_id: uuid.UUID) -> LinkCode:
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=self.link_ttl_seconds)
        for _ in range(3):
            code = new_link_code()
            try:
                async with self.session_factory.begin() as session:
                    session.add(
                        DeviceLinkCode(
                            user_id=user_id,
                            code_hash=keyed_hash(code, self._pepper),
                            expires_at=expires_at,
                            created_at=now,
                        )
                    )
                return LinkCode(code, expires_at)
            except IntegrityError:
                continue
        raise HealthConnectError("Не удалось создать код.", code="LINK_CODE_UNAVAILABLE")

    async def complete_link(
        self,
        *,
        code: str,
        installation_id: str,
        device_name: str,
        device_model: str | None,
        rate_limit_key: str | None = None,
    ) -> LinkedDevice:
        now = datetime.now(UTC)
        normalized_code = code.strip().upper()
        if not installation_id or len(installation_id) > 255:
            raise HealthConnectError(
                "Некорректный идентификатор устройства.", code="INVALID_DEVICE"
            )
        attempt_hash = keyed_hash(f"attempt:{rate_limit_key or installation_id}", self._pepper)
        code_hash = keyed_hash(normalized_code, self._pepper)
        pending_error: HealthConnectError | None = None
        linked_device: LinkedDevice | None = None
        async with self.session_factory.begin() as session:
            repository = HealthConnectRepository(session)
            attempts = await repository.attempts_since(
                attempt_hash,
                now - timedelta(seconds=self.link_attempt_window_seconds),
            )
            if attempts >= self.link_attempt_limit:
                raise HealthConnectError(
                    "Слишком много попыток. Повторите позже.", code="RATE_LIMITED"
                )
            link = await repository.link_code_by_hash(code_hash, for_update=True)
            if link is None:
                repository.add(
                    DeviceLinkAttempt(
                        attempt_key_hash=attempt_hash, attempted_at=now, succeeded=False
                    )
                )
                pending_error = HealthConnectError(
                    "Неверный код связывания.", code="INVALID_LINK_CODE"
                )
            elif link.consumed_at is not None:
                repository.add(
                    DeviceLinkAttempt(
                        attempt_key_hash=attempt_hash, attempted_at=now, succeeded=False
                    )
                )
                pending_error = HealthConnectError("Код уже использован.", code="LINK_CODE_REUSED")
            elif self._as_utc(link.expires_at) <= now:
                repository.add(
                    DeviceLinkAttempt(
                        attempt_key_hash=attempt_hash, attempted_at=now, succeeded=False
                    )
                )
                pending_error = HealthConnectError(
                    "Срок действия кода истек.", code="LINK_CODE_EXPIRED"
                )
            else:
                installation_hash = keyed_hash(installation_id, self._pepper)
                existing_device = await repository.device_by_installation(
                    link.user_id, installation_hash
                )
                device_id = existing_device.id if existing_device is not None else uuid.uuid4()
                token = new_device_token(device_id)
                if existing_device is None:
                    repository.add(
                        Device(
                            id=device_id,
                            user_id=link.user_id,
                            installation_id_hash=installation_hash,
                            name=device_name.strip()[:100] or "Android device",
                            model=device_model.strip()[:100] if device_model else None,
                            token_hash=keyed_hash(token, self._pepper),
                            token_scope=DeviceScope.HEALTH_CONNECT_SYNC,
                            last_sync_status=SyncStatus.NEVER,
                        )
                    )
                else:
                    existing_device.name = device_name.strip()[:100] or "Android device"
                    existing_device.model = device_model.strip()[:100] if device_model else None
                    existing_device.token_hash = keyed_hash(token, self._pepper)
                    existing_device.token_scope = DeviceScope.HEALTH_CONNECT_SYNC
                    existing_device.revoked_at = None
                repository.add(
                    DeviceLinkAttempt(
                        attempt_key_hash=attempt_hash, attempted_at=now, succeeded=True
                    )
                )
                link.consumed_at = now
                repository.add(
                    TelegramOutbox(
                        user_id=link.user_id,
                        event_key=f"device-linked:{device_id}:{code_hash[:16]}",
                        private_chat_id=await repository.private_chat_id(link.user_id),
                        message_text=(
                            "✅ <b>Устройство подключено</b>\n\n"
                            "Откройте Android-приложение, проверьте найденные пробежки "
                            "и нажмите «Синхронизировать»."
                        ),
                        available_at=now,
                        created_at=now,
                    )
                )
                linked_device = LinkedDevice(
                    device_id, token, DeviceScope.HEALTH_CONNECT_SYNC.value
                )
        if pending_error is not None:
            raise pending_error
        if linked_device is None:
            raise RuntimeError("Link completion ended without a result")
        return linked_device

    async def status(self, token: str) -> DeviceStatus:
        async with self.session_factory() as session:
            device = await self._authorize(session, token)
            return DeviceStatus(
                device_id=device.id,
                name=device.name,
                model=device.model,
                scope=device.token_scope.value,
                last_sync_cursor=device.last_sync_cursor,
                last_sync_at=device.last_sync_at,
                last_sync_status=device.last_sync_status.value,
                last_sync_error=device.last_sync_error,
            )

    async def devices_for_user(self, telegram_user_id: int) -> tuple[DeviceSummary, ...]:
        async with self.session_factory() as session:
            found = await UserRepository(session).get_by_telegram_id(telegram_user_id)
            if found is None:
                raise HealthConnectError("Сначала выполните /start.", code="USER_NOT_FOUND")
            devices = await HealthConnectRepository(session).devices_for_user(found[0].id)
            return tuple(
                DeviceSummary(
                    device_id=device.id,
                    name=device.name,
                    model=device.model,
                    revoked=device.revoked_at is not None,
                    last_sync_at=device.last_sync_at,
                )
                for device in devices
            )

    async def revoke_for_user(self, telegram_user_id: int, device_id: uuid.UUID) -> None:
        async with self.session_factory.begin() as session:
            found = await UserRepository(session).get_by_telegram_id(telegram_user_id)
            if found is None:
                raise HealthConnectError("Сначала выполните /start.", code="USER_NOT_FOUND")
            device = await HealthConnectRepository(session).device(device_id, for_update=True)
            if device is None or device.user_id != found[0].id:
                raise HealthConnectError("Устройство не найдено.", code="DEVICE_NOT_FOUND")
            device.revoked_at = datetime.now(UTC)

    async def sync(
        self, token: str, runs: tuple[HealthConnectRun, ...], cursor: str | None
    ) -> SyncBatchResult:
        if not runs:
            raise HealthConnectError("Batch не должен быть пустым.", code="EMPTY_BATCH")
        if len(runs) > self.max_batch_size:
            raise HealthConnectError("Batch превышает допустимый размер.", code="BATCH_TOO_LARGE")
        async with self.session_factory() as session:
            authorized_device = await self._authorize(session, token)
            device_id = authorized_device.id
            user_id = authorized_device.user_id

        ordered_runs = tuple(sorted(runs, key=lambda item: (item.started_at, item.external_id)))
        is_batch = len(ordered_runs) > 1
        results: list[SyncItemResult] = []
        for run in ordered_runs:
            results.append(await self._sync_item(user_id, run, create_outbox=not is_batch))

        errors = [item for item in results if item.state == SyncItemState.ERROR]
        sync_status = (
            SyncStatus.SUCCESS
            if not errors
            else SyncStatus.FAILED
            if len(errors) == len(results)
            else SyncStatus.PARTIAL
        )
        stored_cursor = cursor if not errors else None
        async with self.session_factory.begin() as session:
            stored_device = await HealthConnectRepository(session).device(
                device_id, for_update=True
            )
            if stored_device is None or stored_device.revoked_at is not None:
                raise HealthConnectError("Device token отозван.", code="TOKEN_REVOKED")
            stored_device.last_sync_at = datetime.now(UTC)
            stored_device.last_sync_status = sync_status
            stored_device.last_sync_error = errors[0].error_code if errors else None
            if stored_cursor is not None:
                stored_device.last_sync_cursor = stored_cursor[:255]
            result_cursor = stored_device.last_sync_cursor
        saved_count = sum(item.state == SyncItemState.SAVED for item in results)
        duplicate_count = sum(item.state == SyncItemState.DUPLICATE for item in results)
        error_count = len(errors)
        if is_batch:
            await self._create_batch_summary(
                device_id=device_id,
                user_id=user_id,
                runs=ordered_runs,
                results=tuple(results),
            )
        return SyncBatchResult(
            tuple(results), result_cursor, saved_count, duplicate_count, 0, error_count
        )

    async def _sync_item(
        self, user_id: uuid.UUID, run: HealthConnectRun, *, create_outbox: bool
    ) -> SyncItemResult:
        external_id = run.external_id[:255]
        try:
            if not run.external_id or len(run.external_id) > 255:
                raise HealthConnectError("Некорректный external ID.", code="INVALID_EXTERNAL_ID")
            normalized = self.adapter.normalize(run)
            validate_normalized(normalized)
            self._validate_samples(normalized)
            return await self._persist_item(user_id, normalized, create_outbox=create_outbox)
        except (HealthConnectError, ImportError) as error:
            return SyncItemResult(
                external_id=external_id,
                state=SyncItemState.ERROR,
                error_code=error.code,
                message=str(error),
            )
        except IntegrityError:
            async with self.session_factory() as session:
                existing = await HealthConnectRepository(session).existing_activity(
                    user_id, run.external_id
                )
            if existing is not None:
                return SyncItemResult(
                    external_id=external_id,
                    state=SyncItemState.DUPLICATE,
                    activity_id=existing.id,
                )
            return SyncItemResult(
                external_id=external_id,
                state=SyncItemState.ERROR,
                error_code="PERSISTENCE_CONFLICT",
                message="Не удалось сохранить активность.",
            )
        except Exception:
            logger.exception("Health Connect item failed", extra={"external_id": external_id})
            return SyncItemResult(
                external_id=external_id,
                state=SyncItemState.ERROR,
                error_code="ITEM_FAILED",
                message="Не удалось сохранить активность.",
            )

    async def _persist_item(
        self,
        user_id: uuid.UUID,
        normalized: NormalizedActivity,
        *,
        create_outbox: bool,
    ) -> SyncItemResult:
        series_uri: str | None = None
        series_summary: dict[str, Any] | None = None
        if normalized.track_points:
            series_uri, series_summary = await self._save_series(normalized)
        try:
            async with self.session_factory.begin() as session:
                repository = HealthConnectRepository(session)
                existing = await repository.existing_activity(user_id, normalized.external_id or "")
                if existing is not None:
                    return SyncItemResult(
                        external_id=normalized.external_id or "",
                        state=SyncItemState.DUPLICATE,
                        activity_id=existing.id,
                    )
                user = await session.get(User, user_id)
                if user is None:
                    raise HealthConnectError("Пользователь не найден.", code="USER_NOT_FOUND")
                activity_repository = ActivityRepository(session)
                source = await activity_repository.get_or_create_source(
                    user_id, SourceType.HEALTH_CONNECT
                )
                pace = calculate_pace_sec_per_km(normalized.distance_m, normalized.elapsed_time_sec)
                activity = Activity(
                    user_id=user_id,
                    source_id=source.id,
                    source_type=SourceType.HEALTH_CONNECT,
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
                    avg_cadence_spm=normalized.avg_cadence_spm,
                    elevation_gain_m=normalized.elevation_gain_m,
                    visibility=ActivityVisibility.PRIVATE,
                )
                activity_repository.add(activity)
                await session.flush()
                for split in normalized.splits or build_splits(
                    normalized.distance_m, normalized.elapsed_time_sec
                ):
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
                if series_uri is not None and series_summary is not None:
                    repository.add(
                        ActivitySeries(
                            activity_id=activity.id,
                            series_kind="HEALTH_CONNECT",
                            storage_uri=series_uri,
                            content_encoding="gzip",
                            content_type="application/json",
                            point_count=int(series_summary["point_count"]),
                            summary_json=series_summary,
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
                    user_id, started_from=week_start, started_before=week_end
                )
                report = build_after_run_report(summary, week_stats)
                repository.add(
                    CoachReport(
                        user_id=user_id,
                        activity_id=activity.id,
                        report_type=ReportType.AFTER_RUN,
                        facts_json=report.facts_json,
                        rule_result_json=report.rule_result_json,
                        message_private=report.message,
                    )
                )
                if create_outbox:
                    repository.add(
                        TelegramOutbox(
                            user_id=user_id,
                            activity_id=activity.id,
                            private_chat_id=await repository.private_chat_id(user_id),
                            message_text=report.message,
                            available_at=datetime.now(UTC),
                            created_at=datetime.now(UTC),
                        )
                    )
                return SyncItemResult(
                    external_id=normalized.external_id or "",
                    state=SyncItemState.SAVED,
                    activity_id=activity.id,
                )
        finally:
            if series_uri is not None:
                async with self.session_factory() as session:
                    persisted = await session.scalar(
                        select(ActivitySeries.id).where(ActivitySeries.storage_uri == series_uri)
                    )
                if persisted is None:
                    await self.storage.delete(series_uri)

    async def _create_batch_summary(
        self,
        *,
        device_id: uuid.UUID,
        user_id: uuid.UUID,
        runs: tuple[HealthConnectRun, ...],
        results: tuple[SyncItemResult, ...],
    ) -> None:
        identity = "\n".join(sorted(run.external_id for run in runs))
        batch_key = hashlib.sha256(f"{device_id}\n{identity}".encode()).hexdigest()
        saved_ids = tuple(
            item.activity_id
            for item in results
            if item.state == SyncItemState.SAVED and item.activity_id is not None
        )
        now = datetime.now(UTC)
        async with self.session_factory.begin() as session:
            repository = HealthConnectRepository(session)
            if await repository.sync_batch_by_key(batch_key) is not None:
                return
            user = await session.get(User, user_id)
            if user is None:
                raise HealthConnectError("Пользователь не найден.", code="USER_NOT_FOUND")
            activities: tuple[Activity, ...] = ()
            if saved_ids:
                activities = tuple(
                    (
                        await session.execute(select(Activity).where(Activity.id.in_(saved_ids)))
                    ).scalars()
                )
            saved = sum(item.state == SyncItemState.SAVED for item in results)
            duplicate = sum(item.state == SyncItemState.DUPLICATE for item in results)
            errors = sum(item.state == SyncItemState.ERROR for item in results)
            batch = HealthConnectSyncBatch(
                device_id=device_id,
                user_id=user_id,
                batch_key=batch_key,
                period_start=min(run.started_at for run in runs),
                period_end=max(run.started_at for run in runs),
                found_count=len(runs),
                saved_count=saved,
                duplicate_count=duplicate,
                skipped_count=0,
                error_count=errors,
                created_at=now,
            )
            repository.add(batch)
            await session.flush()
            repository.add(
                TelegramOutbox(
                    user_id=user_id,
                    batch_id=batch.id,
                    private_chat_id=await repository.private_chat_id(user_id),
                    message_text=build_batch_summary(
                        activities,
                        timezone=user.timezone,
                        period_start=batch.period_start,
                        period_end=batch.period_end,
                        found=len(runs),
                        saved=saved,
                        duplicate=duplicate,
                        skipped=0,
                        errors=errors,
                    ),
                    available_at=now,
                    created_at=now,
                )
            )

    async def _authorize(self, session: AsyncSession, token: str) -> Device:
        device_id = token_device_id(token)
        if device_id is None:
            raise HealthConnectError("Некорректный device token.", code="INVALID_TOKEN")
        device = await HealthConnectRepository(session).device(device_id)
        if device is None or not hashes_match(device.token_hash, keyed_hash(token, self._pepper)):
            raise HealthConnectError("Некорректный device token.", code="INVALID_TOKEN")
        if device.revoked_at is not None:
            raise HealthConnectError("Device token отозван.", code="TOKEN_REVOKED")
        if device.token_scope != DeviceScope.HEALTH_CONNECT_SYNC:
            raise HealthConnectError("Device token не имеет нужного scope.", code="INVALID_SCOPE")
        return device

    @staticmethod
    def _validate_samples(normalized: NormalizedActivity) -> None:
        for point in normalized.track_points:
            if point.timestamp.tzinfo is None:
                raise HealthConnectError(
                    "Series timestamp должен иметь timezone.", code="INVALID_SERIES"
                )
            if (point.latitude is None) != (point.longitude is None):
                raise HealthConnectError("Route point неполон.", code="INVALID_ROUTE")
            if point.latitude is not None and not -90 <= point.latitude <= 90:
                raise HealthConnectError("Route point некорректен.", code="INVALID_ROUTE")
            if point.longitude is not None and not -180 <= point.longitude <= 180:
                raise HealthConnectError("Route point некорректен.", code="INVALID_ROUTE")

    async def _save_series(self, normalized: NormalizedActivity) -> tuple[str, dict[str, Any]]:
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
        compressed = gzip.compress(json.dumps(payload, separators=(",", ":")).encode())
        stored = await self.storage.save("series", compressed, ".json.gz")
        return stored.uri, {
            "point_count": len(payload),
            "has_gps": any(point.latitude is not None for point in normalized.track_points),
            "has_hr": any(point.heart_rate is not None for point in normalized.track_points),
            "has_speed": any(point.speed_mps is not None for point in normalized.track_points),
            "has_cadence": any(point.cadence_spm is not None for point in normalized.track_points),
            "has_elevation": any(
                point.elevation_m is not None for point in normalized.track_points
            ),
        }

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @property
    def _pepper(self) -> str:
        if self.security_pepper is None:
            raise HealthConnectError(
                "Health Connect linking is disabled.", code="CONFIGURATION_ERROR"
            )
        return self.security_pepper
