import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.activities.models import DraftInputMethod, ManualActivityDraft
from app.ai.contracts import AiTask
from app.db.base import Base, TimestampMixin


class ExternalAiAccessStatus(StrEnum):
    PENDING = "PENDING"
    ALLOWED = "ALLOWED"
    REVOKED = "REVOKED"


class AiAttemptStatus(StrEnum):
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ExternalAiAccess(TimestampMixin, Base):
    __tablename__ = "external_ai_access"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[ExternalAiAccessStatus] = mapped_column(
        Enum(ExternalAiAccessStatus, native_enum=False, create_constraint=True, length=16),
        default=ExternalAiAccessStatus.PENDING,
    )
    notification_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by_telegram_user_id: Mapped[int | None] = mapped_column(BigInteger)


class AiAttempt(Base):
    __tablename__ = "ai_attempts"
    __table_args__ = (
        Index("ix_ai_attempts_user_created", "user_id", "created_at"),
        Index(
            "ix_ai_attempts_draft_hash_status",
            "draft_id",
            "input_sha256",
            "status",
        ),
        Index("ix_ai_attempts_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(ManualActivityDraft.id, ondelete="CASCADE")
    )
    task: Mapped[AiTask] = mapped_column(
        Enum(AiTask, native_enum=False, create_constraint=True, length=32)
    )
    input_method: Mapped[DraftInputMethod | None] = mapped_column(
        Enum(DraftInputMethod, native_enum=False, create_constraint=True, length=16)
    )
    input_sha256: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    provider_model: Mapped[str] = mapped_column(String(128))
    provider_request_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[AiAttemptStatus] = mapped_column(
        Enum(AiAttemptStatus, native_enum=False, create_constraint=True, length=16)
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
