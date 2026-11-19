import json
from collections.abc import AsyncGenerator
from contextlib import aclosing
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from starlette.responses import JSONResponse, StreamingResponse

from verstehen.api.deps import get_turns
from verstehen.session.events import Notification, TurnEvent
from verstehen.session.titles import title_from_prompt
from verstehen.session.turns import Refused, TurnInput, Turns
from verstehen.store.entries import Entry
from verstehen.store.sessions import Session

Service = Annotated[Turns, Depends(get_turns)]
HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}


class ApiError(BaseModel):
    error: str


class ModelsNotConfigured(ApiError):
    code: Literal["models_not_configured"] = "models_not_configured"
    missing: list[Literal["strong"]]


class TurnInFlight(ApiError):
    code: Literal["turn_in_flight"] = "turn_in_flight"


class NotRunning(BaseModel):
    ok: Literal[False] = False
    reason: Literal["not_running"] = "not_running"


router = APIRouter(responses={400: {"model": ApiError}, 404: {"model": ApiError}})


class TitleInput(BaseModel):
    title: str | None = ""


class SessionItem(BaseModel):
    id: str
    title: str
    kind: Literal["teach"]
    updated_at: datetime
    busy: bool


class SessionList(BaseModel):
    sessions: list[SessionItem]


class SessionDetail(Session):
    entries: list[Entry]
    turn_in_flight: bool
    turn_error: str | None


class Created(BaseModel):
    id: str


class Renamed(BaseModel):
    title: str


class Ok(BaseModel):
    ok: bool = True


def not_found() -> JSONResponse:
    return JSONResponse({"error": "Not found"}, status_code=404)


@router.get("/api/sessions", response_model=SessionList)
async def list_sessions(service: Service) -> SessionList:
    return SessionList(
        sessions=[
            SessionItem(
                **session.model_dump(),
                busy=service.runtimes.get(session.id).run is not None,
            )
            for session in await service.sessions.list()
        ]
    )


@router.post("/api/sessions", response_model=Created)
async def create_session(body: TitleInput, service: Service) -> Created:
    session = await service.sessions.create(
        title_from_prompt(body.title or "Untitled session")
    )
    service.notifications.publish(
        Notification(type="chats-changed", session_id=session.id)
    )
    return Created(id=session.id)


@router.get("/api/sessions/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str, service: Service):
    runtime = service.runtimes.get(session_id)
    async with runtime.lock:
        session = await service.sessions.get(session_id)
        if session is None:
            return not_found()
        entries = await service.entries.list(session_id)
        return SessionDetail(
            **session.model_dump(),
            entries=entries,
            turn_in_flight=runtime.run is not None,
            turn_error=runtime.failure,
        )


@router.patch("/api/sessions/{session_id}", response_model=Renamed)
async def rename_session(session_id: str, body: TitleInput, service: Service):
    if await service.sessions.get(session_id) is None:
        return not_found()
    title = (body.title or "").strip()
    if not title:
        return JSONResponse(
            {"error": "title must be a non-empty string"}, status_code=400
        )
    if not await service.sessions.rename(session_id, title):
        return not_found()
    service.notifications.publish(
        Notification(type="chats-changed", session_id=session_id)
    )
    return Renamed(title=title)


@router.delete(
    "/api/sessions/{session_id}",
    response_model=Ok,
    responses={409: {"model": TurnInFlight}},
)
async def delete_session(session_id: str, service: Service):
    runtime = service.runtimes.get(session_id)
    async with runtime.lock:
        if await service.sessions.get(session_id) is None:
            return not_found()
        if runtime.run is not None:
            return JSONResponse(
                {
                    "error": "A turn is running in this session — try again when it finishes",
                    "code": "turn_in_flight",
                },
                status_code=409,
            )
        await service.sessions.delete(session_id)
        runtime.mark_deleted()
    service.notifications.publish(
        Notification(type="chats-changed", session_id=session_id)
    )
    return Ok()


@router.post(
    "/api/sessions/{session_id}/input",
    response_model=Ok,
    responses={409: {"model": ApiError}, 503: {"model": ModelsNotConfigured}},
)
async def input_session(session_id: str, body: TurnInput, service: Service):
    result = await service.start(session_id, body)
    if isinstance(result, Refused):
        return JSONResponse(result.reason, status_code=result.status)
    return Ok()


@router.post(
    "/api/sessions/{session_id}/abort",
    response_model=Ok,
    responses={409: {"model": NotRunning}},
)
async def abort_session(session_id: str, service: Service):
    if await service.sessions.get(session_id) is None:
        return not_found()
    run = service.runtimes.get(session_id).run
    if run is None:
        return JSONResponse({"ok": False, "reason": "not_running"}, status_code=409)
    run.abort()
    return Ok()


async def turn_frames(session_id: str, service: Turns) -> AsyncGenerator[str]:
    runtime = service.runtimes.get(session_id)
    run = runtime.run
    if run is None:
        if runtime.failure is not None:
            yield frame(TurnEvent(type="error", error_text=runtime.failure))
        yield frame(TurnEvent(type="turn-settled"))
    else:
        async with aclosing(run.subscribe()) as events:
            async for event in events:
                yield frame(event)
    yield "data: [DONE]\n\n"


def frame(event: TurnEvent) -> str:
    return f"data: {event.model_dump_json(exclude_none=True)}\n\n"


@router.get(
    "/api/sessions/{session_id}/stream",
    response_model=TurnEvent,
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "schema": {"$ref": "#/components/schemas/TurnEvent"}
                }
            }
        }
    },
)
async def stream_session(session_id: str, service: Service):
    if await service.sessions.get(session_id) is None:
        return not_found()
    return StreamingResponse(
        turn_frames(session_id, service),
        media_type="text/event-stream",
        headers=HEADERS,
    )


@router.get(
    "/api/events",
    response_model=Notification,
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "schema": {"$ref": "#/components/schemas/Notification"}
                }
            }
        }
    },
)
async def events(service: Service):
    return StreamingResponse(
        notification_frames(service), media_type="text/event-stream", headers=HEADERS
    )


async def notification_frames(service: Turns) -> AsyncGenerator[str]:
    async with aclosing(service.notifications.subscribe()) as events:
        async for event in events:
            if event is None:
                yield ": ping\n\n"
            else:
                payload = json.dumps({"session_id": event.session_id})
                yield f"event: {event.type}\ndata: {payload}\n\n"
