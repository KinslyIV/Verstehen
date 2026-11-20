import json
from collections.abc import AsyncGenerator
from contextlib import aclosing
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse, StreamingResponse

from verstehen.api.deps import get_session_service, get_turn_service
from verstehen.session.events import Notification, TurnEvent
from verstehen.session.results import Refused
from verstehen.session.sessions import SessionService
from verstehen.session.turns import TurnInput, TurnService
from verstehen.store.entries import Entry
from verstehen.store.sessions import Session
from verstehen.store.settings import ModelPick, SlotName
from verstehen.teaching.questions.inputs import DismissInput

SessionServiceDependency = Annotated[SessionService, Depends(get_session_service)]
TurnServiceDependency = Annotated[TurnService, Depends(get_turn_service)]
HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}


class ApiError(BaseModel):
    error: str


class ModelsNotConfigured(ApiError):
    code: Literal["models_not_configured"] = "models_not_configured"
    missing: list[SlotName]


class ModelUnavailable(ApiError):
    code: Literal["model_unavailable"] = "model_unavailable"
    reason: str


class TurnInFlight(ApiError):
    code: Literal["turn_in_flight"] = "turn_in_flight"


class JobsRunning(ApiError):
    code: Literal["jobs_running"] = "jobs_running"
    job_ids: list[str]


class NotRunning(BaseModel):
    ok: Literal[False] = False
    reason: Literal["not_running"] = "not_running"


router = APIRouter(responses={400: {"model": ApiError}, 404: {"model": ApiError}})


class TitleInput(BaseModel):
    title: str | None = ""


class SessionInput(TitleInput):
    model: ModelPick | None = None


class SessionItem(BaseModel):
    id: str
    title: str
    kind: Literal["teach"]
    updated_at: datetime
    busy: bool
    compacting: bool = Field(default_factory=lambda: False)


class SessionList(BaseModel):
    sessions: list[SessionItem]


class SessionDetail(Session):
    entries: list[Entry]
    turn_in_flight: bool
    turn_error: str | None
    compacting: bool = Field(default_factory=lambda: False)
    artifact_views: dict[str, bool] = Field(default_factory=dict)


class SteerInput(BaseModel):
    id: str
    text: str


class ArtifactViewInput(BaseModel):
    inverted: bool


class Created(BaseModel):
    id: str


class Renamed(BaseModel):
    title: str


class Ok(BaseModel):
    ok: bool = True


class ParkedDismissal(Ok):
    parked: Literal[True] = True


@router.get("/api/sessions", response_model=SessionList)
async def list_sessions(session_service: SessionServiceDependency) -> SessionList:
    result = await session_service.list()
    return SessionList(
        sessions=[
            SessionItem(
                **item.session.model_dump(), busy=item.busy, compacting=item.compacting
            )
            for item in result
        ]
    )


@router.post(
    "/api/sessions",
    response_model=Created,
    responses={503: {"model": ModelUnavailable}},
)
async def create_session(body: SessionInput, session_service: SessionServiceDependency):
    session = await session_service.create(body.title, body.model)
    if isinstance(session, Refused):
        return JSONResponse(session.reason, status_code=session.status)
    return Created(id=session.id)


@router.get("/api/sessions/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str, session_service: SessionServiceDependency):
    result = await session_service.get(session_id)
    if isinstance(result, Refused):
        return JSONResponse(result.reason, status_code=result.status)
    return SessionDetail(
        **result.session.model_dump(),
        entries=result.entries,
        turn_in_flight=result.turn_in_flight,
        turn_error=result.turn_error,
        compacting=result.compacting,
        artifact_views=result.artifact_views,
    )


@router.patch(
    "/api/sessions/{session_id}",
    response_model=Renamed,
    responses={503: {"model": ModelUnavailable}},
)
async def rename_session(
    session_id: str, body: SessionInput, session_service: SessionServiceDependency
):
    result = await session_service.update(
        session_id, body.title, body.model, "title" in body.model_fields_set
    )
    if isinstance(result, Refused):
        return JSONResponse(result.reason, status_code=result.status)
    return Renamed(title=result)


@router.delete(
    "/api/sessions/{session_id}",
    response_model=Ok,
    responses={409: {"model": TurnInFlight | JobsRunning}},
)
async def delete_session(session_id: str, session_service: SessionServiceDependency):
    result = await session_service.delete(session_id)
    if isinstance(result, Refused):
        return JSONResponse(result.reason, status_code=result.status)
    return Ok()


@router.post(
    "/api/sessions/{session_id}/input",
    response_model=Ok,
    responses={
        409: {"model": ApiError},
        503: {"model": ModelsNotConfigured | ModelUnavailable},
    },
)
async def input_session(
    session_id: str, body: TurnInput, turn_service: TurnServiceDependency
):
    if body.type == "steers":
        return JSONResponse({"error": "unknown input type: steers"}, status_code=400)
    result = await turn_service.start(session_id, body)
    if isinstance(result, Refused):
        return JSONResponse(result.reason, status_code=result.status)
    return Ok()


@router.post(
    "/api/sessions/{session_id}/steer",
    response_model=Ok,
    responses={409: {"model": ApiError}},
)
async def steer_session(
    session_id: str, body: SteerInput, turn_service: TurnServiceDependency
):
    result = await turn_service.delivery_service.steer(session_id, body.id, body.text)
    if isinstance(result, Refused):
        return JSONResponse(result.reason, status_code=result.status)
    return Ok()


@router.put("/api/sessions/{session_id}/artifact-views/{entry_id}", response_model=Ok)
async def put_artifact_view(
    session_id: str,
    entry_id: str,
    body: ArtifactViewInput,
    session_service: SessionServiceDependency,
):
    result = await session_service.set_artifact_view(
        session_id, entry_id, body.inverted
    )
    if isinstance(result, Refused):
        return JSONResponse(result.reason, status_code=result.status)
    return Ok()


@router.post(
    "/api/sessions/{session_id}/dismiss",
    response_model=Ok,
    responses={202: {"model": ParkedDismissal}},
)
async def dismiss_question(
    session_id: str, body: DismissInput, turn_service: TurnServiceDependency
):
    parked = await turn_service.dismiss(session_id, body)
    if isinstance(parked, Refused):
        return JSONResponse(parked.reason, status_code=parked.status)
    if parked:
        return JSONResponse(ParkedDismissal().model_dump(), status_code=202)
    return Ok()


@router.post(
    "/api/sessions/{session_id}/abort",
    response_model=Ok,
    responses={409: {"model": NotRunning}},
)
async def abort_session(session_id: str, session_service: SessionServiceDependency):
    result = await session_service.abort(session_id)
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
async def stream_session(session_id: str, session_service: SessionServiceDependency):
    result = await session_service.stream(session_id)
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
async def events(session_service: SessionServiceDependency):
    return StreamingResponse(
        notification_frames(session_service.subscribe()),
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
                payload = json.dumps(
                    event.model_dump(exclude={"type"}, exclude_none=True)
                )
                yield f"event: {event.type}\ndata: {payload}\n\n"
