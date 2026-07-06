import hmac
import uuid
from datetime import datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from app.ingestion.schemas import ImportError, ImportOverrides, ImportPreview
from app.services import AppServices

router = APIRouter(prefix="/imports", tags=["imports"])


class OverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    started_at: datetime | None = None
    distance_m: int | None = Field(default=None)
    elapsed_time_sec: int | None = Field(default=None)
    moving_time_sec: int | None = Field(default=None)
    title: str | None = None


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overrides: OverrideRequest | None = None
    accept_possible_duplicate: bool = False


def get_services(request: Request) -> AppServices:
    return cast(AppServices, request.app.state.services)


def authorize_import_api(
    request: Request,
    token: Annotated[str | None, Header(alias="X-Idaten-Import-Token")] = None,
) -> None:
    expected = request.app.state.settings.api_token
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Import API is disabled.",
        )
    if token is None or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid import token.")


ImportAuth = Annotated[None, Depends(authorize_import_api)]
Services = Annotated[AppServices, Depends(get_services)]
TelegramUserId = Annotated[int, Header(alias="X-Telegram-User-Id")]


@router.post("")
async def upload_import(
    _auth: ImportAuth,
    services: Services,
    telegram_user_id: TelegramUserId,
    file: Annotated[UploadFile, File()],
) -> dict[str, object]:
    content = await file.read(services.imports.max_upload_bytes + 1)
    try:
        preview = await services.imports.upload_for_user(
            telegram_user_id,
            filename=file.filename or "activity",
            media_type=file.content_type,
            content=content,
        )
    except ImportError as error:
        raise _http_error(error) from error
    return _preview_response(preview)


@router.get("")
async def import_history(
    _auth: ImportAuth, services: Services, telegram_user_id: TelegramUserId
) -> list[dict[str, object]]:
    try:
        items = await services.imports.history(telegram_user_id)
    except ImportError as error:
        raise _http_error(error) from error
    return [
        {
            "import_id": str(item.import_id),
            "filename": item.filename,
            "status": item.status,
            "source_type": item.source_type.value if item.source_type else None,
            "created_at": item.created_at.isoformat(),
            "activity_id": str(item.activity_id) if item.activity_id else None,
            "error_code": item.error_code,
        }
        for item in items
    ]


@router.get("/{import_id}")
async def get_import_preview(
    import_id: uuid.UUID,
    _auth: ImportAuth,
    services: Services,
    telegram_user_id: TelegramUserId,
) -> dict[str, object]:
    try:
        preview = await services.imports.preview_for_user(telegram_user_id, import_id)
    except ImportError as error:
        raise _http_error(error) from error
    return _preview_response(preview)


@router.post("/{import_id}/confirm")
async def confirm_import(
    import_id: uuid.UUID,
    request_body: ConfirmRequest,
    _auth: ImportAuth,
    services: Services,
    telegram_user_id: TelegramUserId,
) -> dict[str, object]:
    overrides = None
    if request_body.overrides is not None:
        values = request_body.overrides
        overrides = ImportOverrides(
            started_at=values.started_at,
            distance_m=values.distance_m,
            elapsed_time_sec=values.elapsed_time_sec,
            moving_time_sec=values.moving_time_sec,
            title=values.title,
        )
    try:
        result = await services.imports.confirm(
            telegram_user_id,
            import_id,
            overrides=overrides,
            accept_possible_duplicate=request_body.accept_possible_duplicate,
        )
    except ImportError as error:
        raise _http_error(error) from error
    return {
        "import_id": str(result.import_id),
        "activity_id": str(result.activity_id),
        "created": result.created,
        "report_message": result.report_message,
    }


def _preview_response(preview: ImportPreview) -> dict[str, object]:
    return {
        "import_id": str(preview.import_id),
        "source_type": preview.source_type.value,
        "started_at": preview.started_at.isoformat(),
        "distance_m": preview.distance_m,
        "elapsed_time_sec": preview.elapsed_time_sec,
        "title": preview.title,
        "exact_duplicate_activity_id": (
            str(preview.exact_duplicate_activity_id)
            if preview.exact_duplicate_activity_id
            else None
        ),
        "duplicate_candidates": [
            {
                "activity_id": str(candidate.activity_id),
                "started_at": candidate.started_at.isoformat(),
                "distance_m": candidate.distance_m,
                "elapsed_time_sec": candidate.elapsed_time_sec,
            }
            for candidate in preview.duplicate_candidates
        ],
    }


def _http_error(error: ImportError) -> HTTPException:
    if error.code == "UPLOAD_TOO_LARGE":
        code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    elif error.code in {"USER_NOT_FOUND", "IMPORT_NOT_FOUND"}:
        code = status.HTTP_404_NOT_FOUND
    elif error.code in {"POSSIBLE_DUPLICATE", "INVALID_IMPORT_STATE"}:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail={"code": error.code, "message": str(error)})
