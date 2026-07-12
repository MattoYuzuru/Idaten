import uuid
from dataclasses import fields
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.readiness.domain import (
    CheckInInputSource,
    CheckInPhase,
    CheckInStatus,
)
from app.readiness.models import ReadinessCheckIn
from app.readiness.repository import ReadinessRepository
from app.readiness.schemas import ReadinessDraft, ReadinessError, ReadinessValues
from app.users.models import User
from app.users.repository import UserRepository

VALUE_FIELDS = tuple(field.name for field in fields(ReadinessValues))


class ReadinessService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def start_draft(
        self,
        telegram_user_id: int,
        phase: CheckInPhase,
        *,
        source: CheckInInputSource = CheckInInputSource.MANUAL,
        source_confidence: float | None = None,
        linked_activity_id: uuid.UUID | None = None,
        prefill: ReadinessValues | None = None,
        moment: datetime | None = None,
    ) -> ReadinessDraft:
        now = moment or datetime.now(UTC)
        self._validate_values(prefill or ReadinessValues(), phase, confirmed=False)
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            repository = ReadinessRepository(session)
            active = await repository.active_draft(user.id, phase, for_update=True)
            if active is not None and self._utc(active.expires_at) <= now:
                active.status = CheckInStatus.EXPIRED
                active = None
            if active is not None:
                return self._dto(active)
            active = ReadinessCheckIn(
                user_id=user.id,
                phase=phase,
                status=CheckInStatus.DRAFT,
                source=source,
                source_confidence=source_confidence,
                linked_activity_id=linked_activity_id,
                expires_at=now + timedelta(hours=24),
                pending_field="overall_readiness",
            )
            self._assign(active, prefill or ReadinessValues())
            repository.add(active)
            await session.flush()
            return self._dto(active)

    async def update(
        self,
        telegram_user_id: int,
        check_in_id: uuid.UUID,
        values: ReadinessValues,
        *,
        expected_version: int | None = None,
        source: CheckInInputSource | None = None,
        source_confidence: float | None = None,
        moment: datetime | None = None,
    ) -> ReadinessDraft:
        now = moment or datetime.now(UTC)
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            check_in = await self._owned(session, user.id, check_in_id, now, for_update=True)
            if check_in.status != CheckInStatus.DRAFT:
                raise ReadinessError("Подтверждённый check-in нельзя редактировать.")
            if expected_version is not None and check_in.version != expected_version:
                raise ReadinessError("Черновик изменился; обновите preview.")
            self._validate_values(values, check_in.phase, confirmed=False)
            self._assign(check_in, values)
            if source is not None:
                check_in.source = source
            check_in.source_confidence = source_confidence
            check_in.version += 1
            return self._dto(check_in)

    async def clear_optional(
        self, telegram_user_id: int, check_in_id: uuid.UUID, field: str
    ) -> ReadinessDraft:
        if field not in {"motivation", "sleep", "available_time", "session_rpe"}:
            raise ReadinessError("Это поле нельзя очистить.")
        now = datetime.now(UTC)
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            check_in = await self._owned(session, user.id, check_in_id, now, for_update=True)
            if check_in.status != CheckInStatus.DRAFT:
                raise ReadinessError("Черновик уже закрыт.")
            names = {
                "motivation": ("motivation",),
                "sleep": (
                    "sleep_quality",
                    "sleep_duration_sec",
                    "sleep_ended_at",
                    "sleep_summary_id",
                ),
                "available_time": ("available_time_sec",),
                "session_rpe": ("session_rpe",),
            }[field]
            for name in names:
                setattr(check_in, name, None)
            if field == "sleep" and check_in.source == CheckInInputSource.HEALTH_CONNECT:
                check_in.source = CheckInInputSource.MANUAL
            check_in.version += 1
            return self._dto(check_in)

    async def cancel(
        self, telegram_user_id: int, check_in_id: uuid.UUID, *, moment: datetime | None = None
    ) -> ReadinessDraft:
        now = moment or datetime.now(UTC)
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            check_in = await self._owned(session, user.id, check_in_id, now, for_update=True)
            if check_in.status == CheckInStatus.DRAFT:
                check_in.status = CheckInStatus.CANCELLED
                check_in.pending_field = None
                check_in.version += 1
            return self._dto(check_in)

    async def confirm(
        self, telegram_user_id: int, check_in_id: uuid.UUID, *, moment: datetime | None = None
    ) -> ReadinessDraft:
        now = moment or datetime.now(UTC)
        async with self.session_factory.begin() as session:
            user = await self._require_user(session, telegram_user_id)
            check_in = await self._owned(session, user.id, check_in_id, now, for_update=True)
            if check_in.status == CheckInStatus.CONFIRMED:
                return self._dto(check_in)
            if check_in.status != CheckInStatus.DRAFT:
                raise ReadinessError("Черновик уже закрыт.")
            values = self._values(check_in)
            self._validate_values(values, check_in.phase, confirmed=True)
            check_in.status = CheckInStatus.CONFIRMED
            check_in.confirmed_at = now
            check_in.pending_field = None
            check_in.version += 1
            return self._dto(check_in)

    async def get(self, telegram_user_id: int, check_in_id: uuid.UUID) -> ReadinessDraft:
        async with self.session_factory() as session:
            user = await self._require_user(session, telegram_user_id)
            check_in = await self._owned(
                session, user.id, check_in_id, datetime.now(UTC), for_update=False
            )
            return self._dto(check_in)

    @staticmethod
    def _validate_values(values: ReadinessValues, phase: CheckInPhase, *, confirmed: bool) -> None:
        ranges = {
            "overall_readiness": (1, 5),
            "general_fatigue": (0, 10),
            "muscle_soreness": (0, 10),
            "motivation": (1, 5),
            "sleep_quality": (1, 5),
            "sleep_duration_sec": (1, 86_400),
            "external_load": (0, 10),
            "pain_severity": (0, 10),
            "available_time_sec": (1, 86_400),
            "session_rpe": (1, 10),
        }
        for name, (minimum, maximum) in ranges.items():
            value = getattr(values, name)
            if value is not None and not minimum <= value <= maximum:
                raise ReadinessError(f"Некорректное значение {name}.")
        if phase == CheckInPhase.PRE_RUN and values.session_rpe is not None:
            raise ReadinessError("Session RPE допустим только после пробежки.")
        if values.pain_location is not None:
            location = values.pain_location.strip()
            if not location or len(location) > 120:
                raise ReadinessError("Локация боли должна быть от 1 до 120 символов.")
        pain_details = (
            values.pain_severity,
            values.pain_location,
            values.pain_affects_movement,
            values.pain_is_new,
            values.pain_is_worsening,
        )
        if values.pain_present is True and any(value is None for value in pain_details):
            raise ReadinessError("При боли заполните severity, location и уточняющие признаки.")
        if values.pain_present is False and any(value is not None for value in pain_details):
            raise ReadinessError("При отсутствии боли pain details должны быть очищены.")
        if confirmed:
            required = (
                values.overall_readiness,
                values.general_fatigue,
                values.muscle_soreness,
                values.external_load,
                values.pain_present,
                values.illness_symptoms,
            )
            if any(value is None for value in required):
                raise ReadinessError("Заполните обязательные поля check-in.")

    @staticmethod
    def _assign(check_in: ReadinessCheckIn, values: ReadinessValues) -> None:
        for name in VALUE_FIELDS:
            value = getattr(values, name)
            if name == "pain_location" and value is not None:
                value = value.strip()
            setattr(check_in, name, value)

    @staticmethod
    def _values(check_in: ReadinessCheckIn) -> ReadinessValues:
        return ReadinessValues(**{name: getattr(check_in, name) for name in VALUE_FIELDS})

    async def _owned(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        check_in_id: uuid.UUID,
        moment: datetime,
        *,
        for_update: bool,
    ) -> ReadinessCheckIn:
        check_in = await ReadinessRepository(session).by_id(check_in_id, for_update=for_update)
        if check_in is None or check_in.user_id != user_id:
            raise ReadinessError("Check-in не найден.")
        if check_in.status == CheckInStatus.DRAFT and self._utc(check_in.expires_at) <= moment:
            check_in.status = CheckInStatus.EXPIRED
            raise ReadinessError("Черновик истёк; начните check-in заново.")
        return check_in

    @staticmethod
    async def _require_user(session: AsyncSession, telegram_user_id: int) -> User:
        found = await UserRepository(session).get_by_telegram_id(telegram_user_id)
        if found is None:
            raise ReadinessError("Сначала выполните /start.")
        return found[0]

    @classmethod
    def _dto(cls, check_in: ReadinessCheckIn) -> ReadinessDraft:
        return ReadinessDraft(
            check_in.id,
            check_in.phase,
            check_in.status,
            check_in.source,
            check_in.source_confidence,
            cls._values(check_in),
            check_in.linked_activity_id,
            check_in.pending_field,
            cls._utc(check_in.expires_at),
            None if check_in.confirmed_at is None else cls._utc(check_in.confirmed_at),
            check_in.version,
            check_in.telegram_message_id,
        )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
