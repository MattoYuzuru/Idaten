from datetime import datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.imports import authorize_import_api
from app.health_connect.schemas import (
    HealthConnectError,
    HealthConnectRun,
    HealthConnectSample,
    HealthConnectSplit,
)
from app.services import AppServices

router = APIRouter(prefix="/health-connect", tags=["health-connect"])


class LinkStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    telegram_user_id: int


class LinkCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=8, max_length=16)
    installation_id: str = Field(min_length=1, max_length=255)
    device_name: str = Field(min_length=1, max_length=100)
    device_model: str | None = Field(default=None, max_length=100)


class SampleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    latitude: float | None = None
    longitude: float | None = None
    elevation_m: float | None = None
    heart_rate: int | None = None
    speed_mps: float | None = None
    cadence_spm: float | None = None


class SplitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    distance_m: int
    elapsed_time_sec: int
    moving_time_sec: int | None = None


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1, max_length=255)
    started_at: datetime
    timezone: str = Field(min_length=1, max_length=64)
    distance_m: int
    elapsed_time_sec: int
    moving_time_sec: int | None = None
    title: str | None = Field(default=None, max_length=255)
    avg_hr: int | None = None
    max_hr: int | None = None
    splits: tuple[SplitRequest, ...] = ()
    samples: tuple[SampleRequest, ...] = ()


class SyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cursor: str | None = Field(default=None, max_length=255)
    batch_id: str | None = Field(default=None, min_length=1, max_length=64)
    activities: tuple[RunRequest, ...]


def get_services(request: Request) -> AppServices:
    return cast(AppServices, request.app.state.services)


Services = Annotated[AppServices, Depends(get_services)]
ImportAuth = Annotated[None, Depends(authorize_import_api)]
Authorization = Annotated[str | None, Header(alias="Authorization")]


@router.post("/link/start")
async def start_link(
    body: LinkStartRequest, _auth: ImportAuth, services: Services
) -> dict[str, str]:
    try:
        result = await services.health_connect.start_link_for_user(body.telegram_user_id)
    except HealthConnectError as error:
        raise _http_error(error) from error
    return {"code": result.code, "expires_at": result.expires_at.isoformat()}


@router.post("/link/complete")
async def complete_link(
    body: LinkCompleteRequest, request: Request, services: Services
) -> dict[str, str]:
    try:
        result = await services.health_connect.complete_link(
            code=body.code,
            installation_id=body.installation_id,
            device_name=body.device_name,
            device_model=body.device_model,
            rate_limit_key=request.client.host if request.client is not None else None,
        )
    except HealthConnectError as error:
        raise _http_error(error) from error
    return {"device_id": str(result.device_id), "token": result.token, "scope": result.scope}


@router.post("/sync/activities")
async def sync_activities(
    body: SyncRequest, services: Services, authorization: Authorization = None
) -> dict[str, object]:
    token = _bearer_token(authorization)
    runs = tuple(_run_from_request(run) for run in body.activities)
    try:
        result = await services.health_connect.sync(
            token, runs, body.cursor, batch_id=body.batch_id
        )
    except HealthConnectError as error:
        raise _http_error(error) from error
    return {
        "cursor": result.cursor,
        "counts": {
            "saved": result.saved_count,
            "duplicate": result.duplicate_count,
            "skipped": result.skipped_count,
            "error": result.error_count,
        },
        "items": [
            {
                "external_id": item.external_id,
                "status": item.state.value,
                "activity_id": str(item.activity_id) if item.activity_id else None,
                "error_code": item.error_code,
                "message": item.message,
            }
            for item in result.items
        ],
    }


@router.get("/sync/status")
async def sync_status(services: Services, authorization: Authorization = None) -> dict[str, object]:
    token = _bearer_token(authorization)
    try:
        result = await services.health_connect.status(token)
    except HealthConnectError as error:
        raise _http_error(error) from error
    return {
        "device_id": str(result.device_id),
        "name": result.name,
        "model": result.model,
        "scope": result.scope,
        "last_sync_cursor": result.last_sync_cursor,
        "last_sync_at": result.last_sync_at.isoformat() if result.last_sync_at else None,
        "last_sync_status": result.last_sync_status,
        "last_sync_error": result.last_sync_error,
    }


def _run_from_request(run: RunRequest) -> HealthConnectRun:
    return HealthConnectRun(
        external_id=run.external_id,
        started_at=run.started_at,
        timezone=run.timezone,
        distance_m=run.distance_m,
        elapsed_time_sec=run.elapsed_time_sec,
        moving_time_sec=run.moving_time_sec,
        title=run.title,
        avg_hr=run.avg_hr,
        max_hr=run.max_hr,
        splits=tuple(
            HealthConnectSplit(
                index=split.index,
                distance_m=split.distance_m,
                elapsed_time_sec=split.elapsed_time_sec,
                moving_time_sec=split.moving_time_sec,
            )
            for split in run.splits
        ),
        samples=tuple(
            HealthConnectSample(
                timestamp=sample.timestamp,
                latitude=sample.latitude,
                longitude=sample.longitude,
                elevation_m=sample.elevation_m,
                heart_rate=sample.heart_rate,
                speed_mps=sample.speed_mps,
                cadence_spm=sample.cadence_spm,
            )
            for sample in run.samples
        ),
    )


def _bearer_token(value: str | None) -> str:
    scheme, separator, token = (value or "").partition(" ")
    if not separator or scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing device token."
        )
    return token


def _http_error(error: HealthConnectError) -> HTTPException:
    status_code = status.HTTP_400_BAD_REQUEST
    if error.code in {"INVALID_TOKEN"}:
        status_code = status.HTTP_401_UNAUTHORIZED
    elif error.code in {"TOKEN_REVOKED", "INVALID_SCOPE"}:
        status_code = status.HTTP_403_FORBIDDEN
    elif error.code == "USER_NOT_FOUND":
        status_code = status.HTTP_404_NOT_FOUND
    elif error.code in {"LINK_CODE_REUSED", "DEVICE_ALREADY_LINKED"}:
        status_code = status.HTTP_409_CONFLICT
    elif error.code == "BATCH_TOO_LARGE":
        status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    elif error.code == "RATE_LIMITED":
        status_code = status.HTTP_429_TOO_MANY_REQUESTS
    elif error.code == "CONFIGURATION_ERROR":
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HTTPException(
        status_code=status_code,
        detail={"code": error.code, "message": str(error)},
    )
