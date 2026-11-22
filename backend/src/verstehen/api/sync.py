import asyncio
from contextlib import AsyncExitStack
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from verstehen.api.sessions import ApiError, Ok
from verstehen.session.events import Notification, Notifications
from verstehen.session.runtime import RuntimeRegistry
from verstehen.store.sync import (
    AcceptedChange,
    InvalidSyncPayloadError,
    SyncChange,
    SyncStore,
    validate_inbound_change,
)
from verstehen.sync.images import (
    MAX_IMAGE_BYTES,
    enrich_legacy_image_refs,
    extract_image_refs,
    missing_local_images,
    save_verified_image,
)
from verstehen.sync.prompts import (
    make_prompt_tx_hooks,
    scan_prompts,
)


def get_sync_store(request: Request) -> SyncStore:
    return request.app.state.sync_store


SyncStoreDependency = Annotated[SyncStore, Depends(get_sync_store)]

router = APIRouter(responses={401: {"model": ApiError}, 404: {"model": ApiError}})


class SchemaMismatchError(ApiError):
    code: Literal["schema_mismatch"] = "schema_mismatch"
    server_schema_version: int
    client_schema_version: int


class MissingImagesError(ApiError):
    code: Literal["missing_images"] = "missing_images"
    missing: list[str]


class InvalidSyncPayloadResponse(ApiError):
    code: Literal["invalid_sync_payload"] = "invalid_sync_payload"


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
    accepted_changes: list[AcceptedChange] = Field(default_factory=list)


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
    responses={
        400: {"model": InvalidSyncPayloadResponse},
        409: {"model": SchemaMismatchError | MissingImagesError},
    },
)
async def sync_push(
    body: PushRequest,
    request: Request,
    sync_store: SyncStoreDependency,
):
    server_schema = await sync_store.schema_version()
    if body.schema_version != server_schema:
        return _schema_mismatch_response(server_schema, body.schema_version)

    session_ids: set[str] = set()
    try:
        for change in body.changes:
            derived_sid = validate_inbound_change(change)
            if derived_sid is not None:
                session_ids.add(derived_sid)
    except InvalidSyncPayloadError as error:
        return JSONResponse(
            InvalidSyncPayloadResponse(error=str(error)).model_dump(),
            status_code=400,
        )

    data_dir = request.app.state.data_dir
    image_refs = extract_image_refs(body.changes, data_dir)
    missing = await asyncio.to_thread(missing_local_images, data_dir, image_refs)
    if missing:
        return JSONResponse(
            MissingImagesError(
                error="Referenced image blobs must be uploaded before pushing.",
                missing=missing,
            ).model_dump(),
            status_code=409,
        )

    runtimes: RuntimeRegistry = request.app.state.runtimes
    prompt_lock: asyncio.Lock = request.app.state.prompt_lock
    origin_device_id = str(request.state.device_id)
    write_winners, rollback_winners = make_prompt_tx_hooks(data_dir)

    try:
        async with prompt_lock:
            async with AsyncExitStack() as stack:
                for sid in sorted(session_ids):
                    await stack.enter_async_context(runtimes.get(sid).lock)
                busy_sessions = {
                    sid
                    for sid in session_ids
                    if runtimes.get(sid).run is not None
                    or runtimes.get(sid).compaction is not None
                }
                (
                    accepted,
                    skipped,
                    server_seq,
                    summary,
                ) = await sync_store.apply_server_push(
                    body.changes,
                    origin_device_id=origin_device_id,
                    busy_sessions=busy_sessions,
                    on_prompt_winners=write_winners,
                    on_prompt_rollback=rollback_winners,
                )
    except InvalidSyncPayloadError as error:
        return JSONResponse(
            InvalidSyncPayloadResponse(error=str(error)).model_dump(),
            status_code=400,
        )

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
        accepted_changes=summary.accepted_changes,
    )


@router.get(
    "/api/sync/pull",
    response_model=PullResponse,
    responses={409: {"model": SchemaMismatchError}},
)
async def sync_pull(
    request: Request,
    sync_store: SyncStoreDependency,
    schema_version: int = Query(...),
    since: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
):
    server_schema = await sync_store.schema_version()
    if schema_version != server_schema:
        return _schema_mismatch_response(server_schema, schema_version)

    prompt_lock: asyncio.Lock = request.app.state.prompt_lock
    async with prompt_lock:
        scan = await asyncio.to_thread(scan_prompts, request.app.state.data_dir)
        await sync_store.sync_prompt_snapshot(
            scan.files,
            skipped_all=scan.skipped_all,
            skipped_paths=scan.skipped_paths,
        )

    origin_device_id = str(request.state.device_id)
    changes, latest_seq, has_more = await sync_store.list_changes_since(
        since, exclude_device_id=origin_device_id, limit=limit
    )
    changes = await asyncio.to_thread(
        enrich_legacy_image_refs, changes, request.app.state.data_dir
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
