from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.activities.models import (
    DraftInputMethod,
    ManualActivityDraft,
    ManualDraftStatus,
    SourceType,
)
from app.activities.repository import ActivityRepository
from app.assisted.media import validate_image
from app.assisted.models import (
    AssistedAccess,
    AssistedAccessStatus,
    ExtractionAttempt,
    ExtractionAttemptStatus,
)
from app.assisted.provider import ActivityExtractionProvider, ExtractionProviderName
from app.assisted.repository import AssistedRepository
from app.assisted.schemas import (
    CONSENT_VERSION,
    AccessOverview,
    AccessRequestResult,
    AssistedError,
    ExtractedRun,
    ExtractionRequest,
    ExtractionResult,
    InputGate,
    InputGateStatus,
)
from app.users.models import User
from app.users.repository import UserRepository
from app.users.schemas import TelegramIdentity
from app.users.service import UserService


class AssistedActivityService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        user_service: UserService,
        provider: ActivityExtractionProvider,
        *,
        enabled: bool,
        owner_telegram_user_id: int | None,
        max_text_chars: int,
        max_image_bytes: int,
        max_image_pixels: int,
        daily_user_limit: int,
        monthly_global_limit: int,
        timeout_seconds: float,
        retries: int,
    ) -> None:
        self.session_factory = session_factory
        self.user_service = user_service
        self.provider = provider
        self.enabled = enabled
        self.owner_telegram_user_id = owner_telegram_user_id
        self.max_text_chars = max_text_chars
        self.max_image_bytes = max_image_bytes
        self.max_image_pixels = max_image_pixels
        self.daily_user_limit = daily_user_limit
        self.monthly_global_limit = monthly_global_limit
        self.timeout_seconds = timeout_seconds
        self.retries = max(0, retries)

    async def gate(self, identity: TelegramIdentity, method: DraftInputMethod) -> InputGate:
        self._require_assisted_method(method)
        user = await self.user_service.register(identity)
        if not self.enabled or self.provider.name == ExtractionProviderName.NONE:
            return InputGate(InputGateStatus.DISABLED, method)
        async with self.session_factory() as session:
            current = await session.get(User, user.id)
            if current is None:
                raise AssistedError("Пользователь не найден.", code="USER_NOT_FOUND")
            if current.assisted_input_consent_version != CONSENT_VERSION:
                return InputGate(InputGateStatus.CONSENT_REQUIRED, method)
            access = await AssistedRepository(session).access(user.id)
            if access is None or access.status == AssistedAccessStatus.PENDING:
                return InputGate(InputGateStatus.ACCESS_PENDING, method)
            if access.status == AssistedAccessStatus.REVOKED:
                return InputGate(InputGateStatus.ACCESS_REVOKED, method)
        return InputGate(InputGateStatus.READY, method)

    async def accept_consent(self, identity: TelegramIdentity) -> AccessRequestResult:
        if not self.enabled or self.provider.name == ExtractionProviderName.NONE:
            raise AssistedError("Распознавание сейчас недоступно.", code="PROVIDER_DISABLED")
        user = await self.user_service.register(identity)
        now = datetime.now(UTC)
        async with self.session_factory.begin() as session:
            current = await session.get(User, user.id, with_for_update=True)
            if current is None:
                raise AssistedError("Пользователь не найден.", code="USER_NOT_FOUND")
            current.assisted_input_consent_version = CONSENT_VERSION
            current.assisted_input_consented_at = now
            repository = AssistedRepository(session)
            access = await repository.access(user.id, for_update=True)
            created = access is None
            if access is None:
                access = AssistedAccess(user_id=user.id, status=AssistedAccessStatus.PENDING)
                repository.add(access)
            account = await UserRepository(session).get_by_telegram_id(identity.telegram_user_id)
            if account is None:
                raise AssistedError("Telegram account не найден.", code="USER_NOT_FOUND")
            _stored_user, telegram = account
            return AccessRequestResult(
                status=access.status,
                notify_owner=(
                    access.status == AssistedAccessStatus.PENDING
                    and (created or access.notification_sent_at is None)
                ),
                telegram_user_id=telegram.telegram_user_id,
                display_name=current.display_name,
                username=telegram.username,
            )

    async def mark_notification_sent(self, telegram_user_id: int) -> None:
        async with self.session_factory.begin() as session:
            found = await UserRepository(session).get_by_telegram_id(telegram_user_id)
            if found is None:
                return
            access = await AssistedRepository(session).access(found[0].id, for_update=True)
            if access is not None:
                access.notification_sent_at = datetime.now(UTC)

    async def decide_access(
        self,
        owner_telegram_user_id: int,
        target_telegram_user_id: int,
        *,
        allow: bool,
    ) -> AccessOverview:
        self._require_owner(owner_telegram_user_id)
        now = datetime.now(UTC)
        async with self.session_factory.begin() as session:
            found = await UserRepository(session).get_by_telegram_id(target_telegram_user_id)
            if found is None:
                raise AssistedError("Пользователь не найден.", code="USER_NOT_FOUND")
            user, _account = found
            repository = AssistedRepository(session)
            access = await repository.access(user.id, for_update=True)
            if access is None:
                access = AssistedAccess(user_id=user.id, status=AssistedAccessStatus.PENDING)
                repository.add(access)
            access.status = AssistedAccessStatus.ALLOWED if allow else AssistedAccessStatus.REVOKED
            access.decided_at = now
            access.decided_by_telegram_user_id = owner_telegram_user_id
            return AccessOverview(
                telegram_user_id=target_telegram_user_id,
                status=access.status,
                consent_current=user.assisted_input_consent_version == CONSENT_VERSION,
            )

    async def access_overview(
        self, owner_telegram_user_id: int, target_telegram_user_id: int
    ) -> AccessOverview:
        self._require_owner(owner_telegram_user_id)
        async with self.session_factory() as session:
            found = await UserRepository(session).get_by_telegram_id(target_telegram_user_id)
            if found is None:
                raise AssistedError("Пользователь не найден.", code="USER_NOT_FOUND")
            user, _account = found
            access = await AssistedRepository(session).access(user.id)
            return AccessOverview(
                telegram_user_id=target_telegram_user_id,
                status=access.status if access else None,
                consent_current=user.assisted_input_consent_version == CONSENT_VERSION,
            )

    async def start_draft(self, telegram_user_id: int, method: DraftInputMethod) -> uuid.UUID:
        self._require_assisted_method(method)
        async with self.session_factory.begin() as session:
            user = await self._require_allowed_user(session, telegram_user_id)
            repository = ActivityRepository(session)
            active = await repository.active_manual_draft(user.id)
            if active is not None:
                active.status = ManualDraftStatus.CANCELLED
                await session.flush()
            draft = ManualActivityDraft(
                user_id=user.id,
                status=ManualDraftStatus.ACTIVE,
                input_method=method,
                source_type=(
                    SourceType.TEXT if method == DraftInputMethod.TEXT else SourceType.SCREENSHOT
                ),
                timezone=user.timezone,
                date_confirmed=False,
                start_time_known=False,
                pending_field="assisted_input",
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
            session.add(draft)
            await session.flush()
            return draft.id

    async def extract_text(
        self, telegram_user_id: int, draft_id: uuid.UUID, text: str
    ) -> uuid.UUID:
        normalized = text.strip()
        if not normalized or len(normalized) > self.max_text_chars:
            raise AssistedError("Текст пустой или слишком длинный.", code="TEXT_SIZE")
        return await self._extract(
            telegram_user_id,
            draft_id,
            normalized.encode(),
            text=normalized,
            image=None,
            media_type=None,
        )

    async def extract_image(
        self,
        telegram_user_id: int,
        draft_id: uuid.UUID,
        content: bytes,
        declared_media_type: str | None,
    ) -> uuid.UUID:
        media_type = validate_image(
            content,
            declared_media_type,
            max_bytes=self.max_image_bytes,
            max_pixels=self.max_image_pixels,
        )
        return await self._extract(
            telegram_user_id,
            draft_id,
            content,
            text=None,
            image=content,
            media_type=media_type,
        )

    def validate_declared_image_size(self, size_bytes: int | None) -> None:
        if size_bytes is not None and size_bytes > self.max_image_bytes:
            raise AssistedError("Изображение превышает допустимый размер.", code="IMAGE_SIZE")

    async def pending_input(
        self, telegram_user_id: int, method: DraftInputMethod
    ) -> uuid.UUID | None:
        async with self.session_factory() as session:
            found = await UserRepository(session).get_by_telegram_id(telegram_user_id)
            if found is None:
                return None
            draft = await ActivityRepository(session).active_manual_draft(found[0].id)
            if (
                draft is None
                or draft.input_method != method
                or draft.pending_field != "assisted_input"
            ):
                return None
            return draft.id

    @property
    def owner_chat_id(self) -> int | None:
        return self.owner_telegram_user_id

    async def _extract(
        self,
        telegram_user_id: int,
        draft_id: uuid.UUID,
        digest_content: bytes,
        *,
        text: str | None,
        image: bytes | None,
        media_type: str | None,
    ) -> uuid.UUID:
        digest = hashlib.sha256(digest_content).hexdigest()
        now = datetime.now(UTC)
        async with self.session_factory.begin() as session:
            user = await self._require_allowed_user(session, telegram_user_id)
            draft = await ActivityRepository(session).manual_draft(draft_id, for_update=True)
            if (
                draft is None
                or draft.user_id != user.id
                or draft.status != ManualDraftStatus.ACTIVE
            ):
                raise AssistedError("Черновик не найден.", code="DRAFT_NOT_FOUND")
            if draft.input_method == DraftInputMethod.TEXT and text is None:
                raise AssistedError("Ожидалось текстовое описание.", code="INPUT_METHOD")
            if draft.input_method == DraftInputMethod.SCREENSHOT and image is None:
                raise AssistedError("Ожидался скриншот.", code="INPUT_METHOD")
            repository = AssistedRepository(session)
            await self._check_limits(repository, user, now)
            succeeded = await repository.successful_attempt(draft.id, digest)
            if succeeded is not None:
                return draft.id
            attempt = ExtractionAttempt(
                user_id=user.id,
                draft_id=draft.id,
                input_method=draft.input_method,
                input_sha256=digest,
                provider=self.provider.name.value,
                provider_model=self.provider.model,
                status=ExtractionAttemptStatus.PROCESSING,
                created_at=now,
            )
            repository.add(attempt)
            await session.flush()
            attempt_id = attempt.id
            timezone = user.timezone
            method = draft.input_method

        request = ExtractionRequest(
            method=method,
            timezone=timezone,
            local_date=now.astimezone(ZoneInfo(timezone)).date(),
            text=text,
            image=image,
            media_type=media_type,
        )
        try:
            result = await self._call_provider(request)
            if not result.run.is_run:
                raise AssistedError("Не удалось распознать пробежку.", code="NOT_A_RUN")
            self._validate_extracted(result.run)
            if result.provider_request_id is not None and len(result.provider_request_id) > 128:
                raise AssistedError(
                    "Provider вернул некорректный request ID.", code="PROVIDER_RESPONSE"
                )
        except AssistedError as error:
            await self._finish_failed(attempt_id, error.code)
            raise

        try:
            async with self.session_factory.begin() as session:
                user = await self._require_allowed_user(session, telegram_user_id)
                draft = await ActivityRepository(session).manual_draft(draft_id, for_update=True)
                if (
                    draft is None
                    or draft.user_id != user.id
                    or draft.status != ManualDraftStatus.ACTIVE
                ):
                    raise AssistedError("Черновик закрыт.", code="DRAFT_NOT_FOUND")
                self._apply_extracted(draft, result.run, request.local_date)
                draft.pending_field = None
                draft.input_sha256 = digest
                draft.provider = self.provider.name.value
                draft.provider_model = self.provider.model
                draft.provider_request_id = result.provider_request_id
                draft.version += 1
                stored_attempt = await AssistedRepository(session).attempt_by_id(
                    attempt_id, for_update=True
                )
                if stored_attempt is None:
                    raise AssistedError("Attempt не найден.", code="ATTEMPT_NOT_FOUND")
                stored_attempt.status = ExtractionAttemptStatus.SUCCEEDED
                stored_attempt.provider_request_id = result.provider_request_id
                stored_attempt.finished_at = datetime.now(UTC)
                return draft.id
        except AssistedError as error:
            await self._finish_failed(attempt_id, error.code)
            raise

    async def _call_provider(self, request: ExtractionRequest) -> ExtractionResult:
        for attempt_number in range(self.retries + 1):
            try:
                return await asyncio.wait_for(
                    self.provider.extract(request), timeout=self.timeout_seconds
                )
            except TimeoutError as error:
                if attempt_number == self.retries:
                    raise AssistedError(
                        "Распознавание не ответило вовремя.", code="PROVIDER_TIMEOUT"
                    ) from error
            except AssistedError:
                if attempt_number == self.retries:
                    raise
            except Exception as error:
                if attempt_number == self.retries:
                    raise AssistedError(
                        "Provider временно недоступен.", code="PROVIDER_FAILED"
                    ) from error
        raise AssistedError("Provider недоступен.", code="PROVIDER_FAILED")

    async def _finish_failed(self, attempt_id: uuid.UUID, error_code: str) -> None:
        async with self.session_factory.begin() as session:
            attempt = await AssistedRepository(session).attempt_by_id(attempt_id, for_update=True)
            if attempt is not None:
                attempt.status = ExtractionAttemptStatus.FAILED
                attempt.error_code = error_code
                attempt.finished_at = datetime.now(UTC)

    async def _check_limits(
        self, repository: AssistedRepository, user: User, now: datetime
    ) -> None:
        zone = ZoneInfo(user.timezone)
        local = now.astimezone(zone)
        day_start = datetime.combine(local.date(), time.min, zone).astimezone(UTC)
        day_end = day_start + timedelta(days=1)
        utc_now = now.astimezone(UTC)
        month_start = datetime(utc_now.year, utc_now.month, 1, tzinfo=UTC)
        if utc_now.month == 12:
            month_end = datetime(utc_now.year + 1, 1, 1, tzinfo=UTC)
        else:
            month_end = datetime(utc_now.year, utc_now.month + 1, 1, tzinfo=UTC)
        if (
            await repository.user_attempt_count(
                user.id, started_from=day_start, started_before=day_end
            )
            >= self.daily_user_limit
        ):
            raise AssistedError("Дневной лимит распознаваний исчерпан.", code="DAILY_LIMIT")
        if (
            await repository.global_attempt_count(
                started_from=month_start,
                started_before=month_end,
            )
            >= self.monthly_global_limit
        ):
            raise AssistedError("Месячный лимит распознаваний исчерпан.", code="MONTHLY_LIMIT")

    async def _require_allowed_user(self, session: AsyncSession, telegram_user_id: int) -> User:
        if not self.enabled or self.provider.name == ExtractionProviderName.NONE:
            raise AssistedError("Распознавание сейчас недоступно.", code="PROVIDER_DISABLED")
        found = await UserRepository(session).get_by_telegram_id(telegram_user_id)
        if found is None:
            raise AssistedError("Сначала выполните /start.", code="USER_NOT_FOUND")
        user, _account = found
        if user.assisted_input_consent_version != CONSENT_VERSION:
            raise AssistedError("Требуется согласие на внешнюю обработку.", code="CONSENT_REQUIRED")
        access = await AssistedRepository(session).access(user.id)
        if access is None or access.status != AssistedAccessStatus.ALLOWED:
            raise AssistedError("Доступ к распознаванию не выдан.", code="ACCESS_DENIED")
        return user

    def _require_owner(self, telegram_user_id: int) -> None:
        if self.owner_telegram_user_id is None or telegram_user_id != self.owner_telegram_user_id:
            raise AssistedError("Команда доступна только владельцу.", code="OWNER_REQUIRED")

    @staticmethod
    def _require_assisted_method(method: DraftInputMethod) -> None:
        if method not in {DraftInputMethod.TEXT, DraftInputMethod.SCREENSHOT}:
            raise AssistedError("Неизвестный способ ввода.", code="INPUT_METHOD")

    @staticmethod
    def _validate_extracted(run: ExtractedRun) -> None:
        if run.distance_m is not None and not 0 < run.distance_m <= 500_000:
            raise AssistedError("Некорректная дистанция.", code="INVALID_DISTANCE")
        if run.elapsed_time_sec is not None and not 0 < run.elapsed_time_sec <= 604_800:
            raise AssistedError("Некорректная длительность.", code="INVALID_DURATION")
        if run.moving_time_sec is not None and (
            run.moving_time_sec <= 0
            or run.elapsed_time_sec is None
            or run.moving_time_sec > run.elapsed_time_sec
        ):
            raise AssistedError("Некорректное moving time.", code="INVALID_MOVING_TIME")
        if run.title is not None and len(run.title) > 255:
            raise AssistedError("Название слишком длинное.", code="INVALID_TITLE")
        for value in (run.avg_hr, run.max_hr):
            if value is not None and not 20 <= value <= 260:
                raise AssistedError("Некорректный пульс.", code="INVALID_HR")
        if run.avg_hr is not None and run.max_hr is not None and run.avg_hr > run.max_hr:
            raise AssistedError("Некорректный пульс.", code="INVALID_HR")
        if run.avg_cadence_spm is not None and not 30 <= run.avg_cadence_spm <= 300:
            raise AssistedError("Некорректный каденс.", code="INVALID_CADENCE")
        if run.elevation_gain_m is not None and not 0 <= run.elevation_gain_m <= 20_000:
            raise AssistedError("Некорректный набор высоты.", code="INVALID_ELEVATION")

    @staticmethod
    def _apply_extracted(
        draft: ManualActivityDraft, run: ExtractedRun, reference_date: date
    ) -> None:
        draft.distance_m = run.distance_m
        draft.elapsed_time_sec = run.elapsed_time_sec
        draft.moving_time_sec = run.moving_time_sec
        draft.avg_hr = run.avg_hr
        draft.max_hr = run.max_hr
        draft.avg_cadence_spm = run.avg_cadence_spm
        draft.elevation_gain_m = run.elevation_gain_m
        draft.title = run.title
        zone = ZoneInfo(draft.timezone)
        if run.local_date is None:
            draft.started_at = (
                datetime.combine(reference_date, run.local_time, zone)
                if run.local_time is not None
                else None
            )
            draft.date_confirmed = False
            draft.start_time_known = run.local_time is not None
            return
        local_time = run.local_time or time(hour=12)
        draft.started_at = datetime.combine(run.local_date, local_time, zone)
        draft.date_confirmed = True
        draft.start_time_known = run.local_time is not None
