from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from starlette.responses import JSONResponse

from verstehen.api.sessions import ApiError
from verstehen.store.sync import SyncStatus, SyncStore
from verstehen.sync.service import SyncService


def get_sync_service(request: Request) -> SyncService:
    return request.app.state.sync_service


def get_sync_store(request: Request) -> SyncStore:
    return request.app.state.sync_store


SyncServiceDependency = Annotated[SyncService, Depends(get_sync_service)]
SyncStoreDependency = Annotated[SyncStore, Depends(get_sync_store)]

router = APIRouter(responses={400: {"model": ApiError}, 404: {"model": ApiError}})


class SyncStatusResponse(BaseModel):
    enabled: bool
    device_id: str
    server_url: str | None
    status: SyncStatus
    last_pushed_seq: int
    last_pulled_seq: int
    last_error: str | None
    last_sync_at: datetime | None
    pending_changes: int
    deferred_sessions: list[str]
    ssh_user: str | None = None
    ssh_port: int | None = None
    server_device_id: str | None = None
    device_identity_missing: bool = False


async def build_sync_status(
    sync_store: SyncStore, sync_service: SyncService
) -> SyncStatusResponse:
    state = await sync_store.read_state()
    pending = await sync_store.count_pending_push()
    enabled = bool(state.server_url and sync_service.credentials_store.sync_token())
    return SyncStatusResponse(
        enabled=enabled,
        device_id=state.device_id,
        server_url=state.server_url,
        status=state.status,
        last_pushed_seq=state.last_pushed_seq,
        last_pulled_seq=state.last_pulled_seq,
        last_error=state.last_error,
        last_sync_at=state.last_sync_at,
        pending_changes=pending,
        deferred_sessions=sync_service.deferred_sessions,
        ssh_user=state.ssh_user,
        ssh_port=state.ssh_port,
        server_device_id=state.server_device_id,
        device_identity_missing=enabled and state.server_device_id is None,
    )


@router.get("/api/sync/status", response_model=SyncStatusResponse)
async def get_sync_status(
    sync_store: SyncStoreDependency,
    sync_service: SyncServiceDependency,
) -> SyncStatusResponse:
    return await build_sync_status(sync_store, sync_service)


@router.post("/api/sync/now", response_model=SyncStatusResponse)
async def trigger_sync_now(
    sync_store: SyncStoreDependency,
    sync_service: SyncServiceDependency,
):
    state = await sync_store.read_state()
    if not state.server_url or not sync_service.credentials_store.sync_token():
        return JSONResponse(
            {"error": "Sync is not configured."},
            status_code=400,
        )
    await sync_service.sync_now()
    return await build_sync_status(sync_store, sync_service)
