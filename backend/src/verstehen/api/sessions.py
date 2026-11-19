import json
from collections.abc import AsyncGenerator
from contextlib import aclosing
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from starlette.responses import JSONResponse, StreamingResponse

from verstehen.api.deps import get_sessions, get_turns
from verstehen.session.events import Notification, TurnEvent
from verstehen.session.results import Refused
from verstehen.session.sessions import Sessions
from verstehen.session.turns import TurnInput, Turns
from verstehen.store.entries import Entry
from verstehen.store.sessions import Session

Service = Annotated[Sessions, Depends(get_sessions)]
TurnService = Annotated[Turns, Depends(get_turns)]
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


@router.get("/api/sessions", response_model=SessionList)
async def list_sessions(service: Service) -> SessionList:
    result = await service.list()
    return SessionList(
        sessions=[
            SessionItem(**item.session.model_dump(), busy=item.busy) for item in result
        ]
    )


@router.post("/api/sessions", response_model=Created)
async def create_session(body: TitleInput, service: Service) -> Created:
    session = await service.create(body.title)
    return Created(id=session.id)


@router.get("/api/sessions/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str, service: Service):
    result = await service.get(session_id)
    if isinstance(result, Refused):
        return JSONResponse(result.reason, status_code=result.status)
    return SessionDetail(
        **result.session.model_dump(),
        entries=result.entries,
        turn_in_flight=result.turn_in_flight,
        turn_error=result.turn_error,
    )


@router.patch("/api/sessions/{session_id}", response_model=Renamed)
async def rename_session(session_id: str, body: TitleInput, service: Service):
    result = await service.rename(session_id, body.title)
    if isinstance(result, Refused):
        return JSONResponse(result.reason, status_code=result.status)
    return Renamed(title=result)


@router.delete(
    "/api/sessions/{session_id}",
    response_model=Ok,
    responses={409: {"model": TurnInFlight}},
)
async def delete_session(session_id: str, service: Service):
    result = await service.delete(session_id)
    if isinstance(result, Refused):
        return JSONResponse(result.reason, status_code=result.status)
    return Ok()


@router.post(
    "/api/sessions/{session_id}/input",
    response_model=Ok,
    responses={409: {"model": ApiError}, 503: {"model": ModelsNotConfigured}},
)
async def input_session(session_id: str, body: TurnInput, service: TurnService):
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
    result = await service.abort(session_id)
    if isinstance(result, Refused):
        return JSONResponse(result.reason, status_code=result.status)
    return Ok()


async def turn_frames(events: AsyncGenerator[TurnEvent]) -> AsyncGenerator[str]:
    async with aclosing(events):
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
    result = await service.stream(session_id)
    if isinstance(result, Refused):
        return JSONResponse(result.reason, status_code=result.status)
    return StreamingResponse(
        turn_frames(result),
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
        notification_frames(service.subscribe()),
        media_type="text/event-stream",
        headers=HEADERS,
    )


async def notification_frames(
    events: AsyncGenerator[Notification | None],
) -> AsyncGenerator[str]:
    async with aclosing(events):
        async for event in events:
            if event is None:
                yield ": ping\n\n"
            else:
                payload = json.dumps({"session_id": event.session_id})
                yield f"event: {event.type}\ndata: {payload}\n\n"
