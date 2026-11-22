import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from verstehen.api.sessions import ApiError, Ok
from verstehen.session.events import Notification, Notifications
from verstehen.session.runtime import RuntimeRegistry
from verstehen.store.sync import SyncChange, SyncStore
from verstehen.sync.images import MAX_IMAGE_BYTES, save_verified_image
from verstehen.sync.prompts import apply_prompt_change, scan_prompts


def get_sync_store(request: Request) -> SyncStore:
    return request.app.state.sync_store


SyncStoreDependency = Annotated[SyncStore, Depends(get_sync_store)]

router = APIRouter(responses={401: {"model": ApiError}, 404: {"model": ApiError}})


class SchemaMismatchError(ApiError):
    code: Literal["schema_mismatch"] = "schema_mismatch"
    server_schema_version: int
    client_schema_version: int


class PushRequest(BaseModel):
    device_id: str = Field(min_length=1)
    schema_version: int
    changes: list[SyncChange]


class PushResponse(BaseModel):
    accepted: int
    skipped: int
    server_seq: int
    schema_version: int
    deferred_session_ids: list[str] = Field(default_factory=list)


class PullResponse(BaseModel):
    changes: list[SyncChange]
    latest_seq: int
    schema_version: int
    has_more: bool


def _schema_mismatch_response(server_version: int, client_version: int) -> JSONResponse:
    return JSONResponse(
        SchemaMismatchError(
            error=f"Schema version mismatch: server is v{server_version}, client is v{client_version}.",
            server_schema_version=server_version,
            client_schema_version=client_version,
        ).model_dump(),
        status_code=409,
    )


@router.post(
    "/api/sync/push",
    response_model=PushResponse,
    responses={409: {"model": SchemaMismatchError}},
)
async def sync_push(
    body: PushRequest,
    request: Request,
    sync_store: SyncStoreDependency,
):
    server_schema = await sync_store.schema_version()
    if body.schema_version != server_schema:
        return _schema_mismatch_response(server_schema, body.schema_version)

    runtimes: RuntimeRegistry = request.app.state.runtimes
    busy_sessions = {
        sid
        for sid, rt in runtimes.runtimes.items()
        if rt.run is not None or rt.compaction is not None
    }
    accepted, skipped, server_seq, summary = await sync_store.apply_server_push(
        body.changes, busy_sessions=busy_sessions
    )
    data_dir = request.app.state.data_dir
    for change in summary.prompt_changes:
        try:
            rel, digest = await asyncio.to_thread(apply_prompt_change, data_dir, change)
            await sync_store.record_prompt_hash(rel, digest)
        except ValueError:
            pass

    notifications: Notifications = request.app.state.notifications
    for sid in sorted(summary.chats_changed):
        notifications.publish(
            Notification(type="chats-changed", session_id=sid, from_sync=True)
        )
    for sid in sorted(summary.jobs_changed):
        notifications.publish(
            Notification(type="jobs-changed", session_id=sid, from_sync=True)
        )
    for sid in sorted(summary.side_chats_changed):
        notifications.publish(
            Notification(type="side-chats-changed", session_id=sid, from_sync=True)
        )
    if summary.graph_revision is not None:
        notifications.publish(
            Notification(
                type="graph-changed",
                revision=summary.graph_revision,
                from_sync=True,
            )
        )

    return PushResponse(
        accepted=accepted,
        skipped=skipped,
        server_seq=server_seq,
        schema_version=server_schema,
        deferred_session_ids=summary.deferred_session_ids,
    )


@router.get(
    "/api/sync/pull",
    response_model=PullResponse,
    responses={409: {"model": SchemaMismatchError}},
)
async def sync_pull(
    request: Request,
    sync_store: SyncStoreDependency,
    since: int = Query(default=0, ge=0),
    schema_version: int | None = Query(default=None),
    device_id: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
):
    server_schema = await sync_store.schema_version()
    if schema_version is not None and schema_version != server_schema:
        return _schema_mismatch_response(server_schema, schema_version)
    current_prompts = await asyncio.to_thread(scan_prompts, request.app.state.data_dir)
    await sync_store.sync_prompt_snapshot(current_prompts)
    changes, latest_seq, has_more = await sync_store.list_changes_since(
        since, exclude_device_id=device_id, limit=limit
    )
    return PullResponse(
        changes=changes,
        latest_seq=latest_seq,
        schema_version=server_schema,
        has_more=has_more,
    )


@router.post(
    "/api/sync/images/{sha256}.{ext}",
    response_model=Ok,
    responses={400: {"model": ApiError}},
)
async def sync_upload_image(sha256: str, ext: str, request: Request):
    data = await request.body()
    if len(data) > MAX_IMAGE_BYTES:
        return JSONResponse({"error": "Image exceeds 25 MiB."}, status_code=400)
    try:
        await asyncio.to_thread(
            save_verified_image, request.app.state.data_dir, sha256, ext, data
        )
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    return Ok()
