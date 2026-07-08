import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class DeviceScope(StrEnum):
    HEALTH_CONNECT_SYNC = "health_connect:sync"
    STATUS_ONLY = "health_connect:status"


class SyncStatus(StrEnum):
    NEVER = "NEVER"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class DeviceLinkCode(Base):
    __tablename__ = "device_link_codes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DeviceLinkAttempt(Base):
    __tablename__ = "device_link_attempts"
    __table_args__ = (
        Index("ix_device_link_attempts_key_time", "attempt_key_hash", "attempted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    attempt_key_hash: Mapped[str] = mapped_column(String(64))
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    succeeded: Mapped[bool] = mapped_column(default=False)


class Device(TimestampMixin, Base):
    __table_args__ = (
        UniqueConstraint("user_id", "installation_id_hash", name="uq_devices_user_installation"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    installation_id_hash: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_scope: Mapped[DeviceScope] = mapped_column(
        Enum(DeviceScope, native_enum=False, create_constraint=True, length=32)
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_sync_cursor: Mapped[str | None] = mapped_column(String(255))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[SyncStatus] = mapped_column(
        Enum(SyncStatus, native_enum=False, create_constraint=True, length=16),
        default=SyncStatus.NEVER,
    )
    last_sync_error: Mapped[str | None] = mapped_column(String(64))


class HealthConnectSyncBatch(Base):
    __tablename__ = "health_connect_sync_batches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    batch_key: Mapped[str] = mapped_column(String(64), unique=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    found_count: Mapped[int] = mapped_column(Integer)
    saved_count: Mapped[int] = mapped_column(Integer)
    duplicate_count: Mapped[int] = mapped_column(Integer)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class TelegramOutbox(Base):
    __tablename__ = "telegram_outbox"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN activity_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN batch_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN event_key IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="exactly_one_subject",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    activity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE"), unique=True
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("health_connect_sync_batches.id", ondelete="CASCADE"), unique=True
    )
    event_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    private_chat_id: Mapped[int] = mapped_column(BigInteger)
    message_text: Mapped[str] = mapped_column(String(4096))
    status: Mapped[OutboxStatus] = mapped_column(
        Enum(OutboxStatus, native_enum=False, create_constraint=True, length=16),
        default=OutboxStatus.PENDING,
        index=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    telegram_message_id: Mapped[int | None] = mapped_column()
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
